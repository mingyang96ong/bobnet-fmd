import os 
import argparse
import torch
import torch.nn as nn
import torch.optim.lr_scheduler as lr_scheduler 
import numpy as np 
import torch.optim as optim
import torchvision.models as models
import torchvision.transforms as transforms
import time
import matplotlib.pyplot as plt
import pickle 
import albumentations as A

from torch.utils import data 
from RandAugment import RandAugment
# from model import BobNet
from dataset import Flickr
from dataset import MINC
import gc

best_acc = 1e-6
def parse_args(): 
    parser = argparse.ArgumentParser() 
    parser.add_argument("exp_name", help="name of experiment to run")
    parser.add_argument("--batch_size", type = int, help="batch size of the experiment")
    parser.add_argument("--mixup", action="store_true")
    parser.add_argument("--deepalexnet", action="store_true")
    parser.add_argument("--shallowalexnet", action="store_true")
    parser.add_argument("--efficientnet", action="store_true")
    parser.add_argument("--alexnet", action="store_true")
    parser.add_argument("--googlenet", action="store_true")
    parser.add_argument("--vgg19", action="store_true")
    parser.add_argument("--densenet", action="store_true")
    parser.add_argument("--freeze", action="store_true", help="only freeze vgg19 for now")
    parser.add_argument("--aug", action="store_true")
    parser.add_argument("--albumentation", action="store_true")
    parser.add_argument("--minc", action="store_true")
    args = parser.parse_args()
    return args
args = parse_args() 
class Trainer(object):
    def __init__(self, exp):
        self.path = os.path.join(os.getcwd(), 'FMD')
        self.exp_name = exp
        self.device = torch.device('cuda:0') # Change to YAML 
        self.max_epochs = 50 
        self.batch_size = args.batch_size

        self.train_transform = transforms.Compose([
            transforms.Resize((224,224)),
            #transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize((0.485,0.456,0.406),(0.229,0.224,0.225)),
        ])
        self.val_transform = transforms.Compose([
            transforms.Resize((224,224)),
            transforms.ToTensor(),
            transforms.Normalize((0.485,0.456,0.406),(0.229,0.224,0.225)),
            ])

        # Add RandAugment with N, M(hyperparameter) 
        if args.aug:
            print("RandAugment will be run")
            #self.train_transform.transforms.insert(0, RandAugment(1,9))
            self.val_transform = transforms.Compose([
            transforms.Resize((224,224)),
            transforms.ToTensor(),
            transforms.Normalize((0.485,0.456,0.406),(0.229,0.224,0.225)),
        ])
        elif args.albumentation:
            self.train_transform = A.Compose([
                A.CLAHE(),
                A.RandomRotate90(),
                A.Transpose(),
                A.ShiftScaleRotate(shift_limit=0.0625, scale_limit=0.50, rotate_limit=45, p=.75),
                A.Blur(blur_limit=3),
                A.OpticalDistortion(),
                A.GridDistortion(),
                A.HueSaturationValue()
            ])
            self.val_transform = transforms.Compose([
            transforms.Resize((224,224)),
            transforms.ToTensor(),
            transforms.Normalize((0.485,0.456,0.406),(0.229,0.224,0.225)),
            ])


        if args.minc:
            self.train_dataset = MINC(
                path=self.path,
                image_set='train',
                transforms=self.train_transform,
            )
            self.val_dataset = MINC(
                path=self.path,
                image_set='val',
                transforms=self.val_transform,
            )

        else: # Use Flickr
            self.train_dataset = Flickr(
                path=self.path,
                image_set='train',
                transforms=self.train_transform,
                mixup=args.mixup
            )
            self.val_dataset = Flickr(
                path=self.path,
                image_set='val',
                transforms=self.val_transform,
            )
        self.train_loader = data.DataLoader(
            dataset=self.train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=1,
            pin_memory=True,
            drop_last=True,
        )
        self.val_loader = data.DataLoader( 
            dataset=self.val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=1,
            pin_memory=True,
            drop_last=False,
        )
        self.iters_per_epoch = len(self.train_dataset) // self.batch_size 
        self.max_iters = self.max_epochs * self.iters_per_epoch
        # Use efficientnet
        if args.efficientnet:
            from efficientnet_pytorch import EfficientNet
            self.model = EfficientNet.from_pretrained('efficientnet-b0', num_classes=10, image_size=(227,227)).to(self.device)
        elif args.googlenet:
            self.model = torch.hub.load('pytorch/vision:v0.6.0', 'googlenet', pretrained=True)
            self.model.fc = torch.nn.Linear(1024, 10)
            self.model = self.model.to(self.device)
        elif args.vgg19:
            self.model = models.vgg19(pretrained=True)
            self.model.classifier[6].weight = torch.nn.Parameter(self.model.classifier[6].weight[:10])
            self.model.classifier[6].bias = torch.nn.Parameter(self.model.classifier[6].bias[:10])
            self.model.classifier[6].out_features = 10
            self.model = self.model.to(self.device)
            if args.freeze:
                for layer in self.model.features:
                    print("Freezing layer:", layer)
                    layer.require_grad = False
                for idx, layer in enumerate(self.model.classifier):
                    if idx != 6:
                        print("Freezing layer:", layer)
                        layer.require_grad = False
        elif args.alexnet:
            from torchvision.models import alexnet 
            self.model = alexnet(pretrained=True)
            # Change output layer to 10 classes 
            if args.deepalexnet:
                self.model.classifier = torch.nn.Sequential(*self.model.classifier, torch.nn.ReLU(inplace = True),torch.nn.Linear(1000, 10, bias = True))
            elif args.shallowalexnet:
                self.model.classifier = torch.nn.Sequential(*[x for idx, x in enumerate(self.model.classifier) if idx <= 3],torch.nn.Linear(4096, 10, bias = True))
            else:
                self.model.classifier[6] = nn.Linear(4096, 10) 
            self.model = self.model.to(self.device)
        elif args.densenet:
            self.model = models.densenet121(pretrained = True)
            self.model.classifier.weight = torch.nn.Parameter(self.model.classifier.weight[:10])
            self.model.classifier.bias = torch.nn.Parameter(self.model.classifier.bias[:10])
            self.model.classifier.out_features = 10
            self.model = self.model.to(self.device)
        else:
            self.model = BobNet(2).to(self.device)
        
        self.optimizer = optim.SGD(
            self.model.parameters(),
            lr=0.001,
            momentum=0.9,
            weight_decay=1e-4,
        )
        self.lr_scheduler = torch.optim.lr_scheduler.StepLR(self.optimizer, step_size=25, gamma=0.1)
        self.criterion = nn.CrossEntropyLoss().cuda()
        
        # For plotting graphs 
        self.train_acc = []
        self.val_acc = []
        self.train_loss = [] 
        self.val_loss = []

    def train(self, epoch, start_time): 
        total, correct = 0, 0
        iteration = epoch*self.iters_per_epoch if epoch > 0 else 0 
        epoch_loss = 0
        for batch_idx, sample in enumerate(self.train_loader): 
           iteration += 1
           img = sample['img'].to(self.device)
        #    plt.imshow(img[0].cpu().numpy().transpose(1,2,0))
        #    plt.show()
           label = sample['label'].to(self.device)
           outputs = self.model(img) 
           loss = self.criterion(outputs, label) 
           _, predicted = torch.max(outputs.data, 1) 
           total += label.size(0) 
           correct += (predicted == label).sum().item() 

           self.optimizer.zero_grad() 
           loss.backward() 
           self.optimizer.step() 
           #self.lr_scheduler.step() 
           epoch_loss += loss.item()
           if iteration % 10 == 0: 
            print("Epoch: {:d}/{:d} || Iters: {:d}/{:d} || Loss: {:.4f} || lr: {}".format(epoch, self.max_epochs, iteration%(self.iters_per_epoch), self.iters_per_epoch, loss.item(), self.optimizer.param_groups[0]['lr']))
        if epoch%1 == 0: 
            accuracy = 100*correct/total
            save_dict = { 
                "epoch" : epoch, 
                "model" : self.model.state_dict(), 
                "optim" : self.optimizer.state_dict(), 
                }
            save_name = os.path.join(os.getcwd(), 'results', self.exp_name, 'run.pth'.format(epoch))
            torch.save(save_dict, save_name) 
            print("Model is saved: {}".format(save_name))
            # Appending for graph
            self.train_acc.append([])
            self.train_acc[-1].append(accuracy)
            self.train_loss.append([])
            self.train_loss[-1].append(epoch_loss/len(self.train_loader))
            print('Train accuracy: ', '{:.4f}'.format(accuracy))

    def val(self, epoch): 
        total, correct = 0, 0
        global best_acc 
        epoch_loss = 0 
        with torch.no_grad(): 
            for batch_idx, sample in enumerate(self.val_loader): 
                img = sample['img'].to(self.device)
                label = sample['label'].to(self.device) 
                outputs = self.model(img)
                loss = self.criterion(outputs, label)
                epoch_loss += loss.item() 
                _, predicted = torch.max(outputs.data, 1)
                total += label.size(0)
                correct += (predicted == label).sum().item()

            print("Validation loss: {:.4f}".format(epoch_loss/len(self.val_loader)))
        accuracy = 100*correct/total
        print('Validation accuracy: {:.4f}'.format(accuracy))
        # Save model if val_loss lower than best 
        if accuracy > best_acc:
            best_acc = accuracy 
            save_name = os.path.join(os.getcwd(), 'results', self.exp_name, 'best_acc.pth') 
            save_dict = {
                "epoch": epoch,
                "model": self.model.state_dict(),
                "optim": self.optimizer.state_dict(),
                "best_acc": best_acc, 
                }
            torch.save(save_dict, save_name) 
            print("val_acc is higher than best_acc! Model saved to {}".format(save_name))

        self.val_acc.append([])
        self.val_acc[-1].append(accuracy)
        self.val_loss.append([])
        self.val_loss[-1].append(epoch_loss/len(self.val_loader))
        

if __name__ == '__main__':
    t = Trainer(args.exp_name)
    os.makedirs(os.path.join(os.getcwd(), 'results', t.exp_name), exist_ok=True)
    epoch = 0
    start_time = time.time()
    for epoch in range(t.max_epochs):
        t.train(epoch, start_time)
        t.val(epoch)
        t.lr_scheduler.step()
        p = {
            'train_acc': t.train_acc,
            'train_loss': t.train_loss,
            'val_acc': t.val_acc,
            'val_loss': t.val_loss
        }
        with open(os.path.join(os.getcwd(),'results',t.exp_name, 'p.pkl'), 'wb') as handle:
            pickle.dump(p, handle)
        print("Saved plot details to ", os.path.join(os.getcwd(),'results',t.exp_name, 'p.pkl'))
        gc.collect()
