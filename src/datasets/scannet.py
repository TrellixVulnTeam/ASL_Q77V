import torch.utils.data as data
import numpy as np
import torch
import pandas as pd
from torchvision import transforms as tf
from torchvision.transforms import functional as F
import PIL
import random
import scipy
import os
from pathlib import Path
from PIL import Image
import copy 
import time
try:
    from .helper import Augmentation
    from .replay_base import StaticReplayDataset
except Exception:  # ImportError
    from helper import Augmentation
    from replay_base import StaticReplayDataset
import imageio
import pandas
import numpy_indexed as npi
__all__ = ['ScanNet']
def loop_translate(a,d):
  n = np.ndarray(a.shape)
  for k in d:
      n[a == k] = d[k]
  return n

class ScanNet(data.Dataset):
    def __init__(
            self,
            root='/media/dataserver/jonfrey/datasets/scannet_test/',
            mode='train',
            scenes=[],
            output_trafo=None,
            output_size=400,
            degrees=10,
            flip_p=0.5,
            jitter_bcsh=[
                0.3,
                0.3,
                0.3,
                0.05],
            replay = False,
            cfg_replay = {'bins':4, 'elements':100, 'add_p': 0.5, 'replay_p':0.5, 'current_bin': 0},
            data_augmentation= True, data_augmentation_for_replay=True):
        """
        Parameters
        ----------
        root : str, path to the ML-Hypersim folder
        mode : str, option ['train','val]
        """
        # super.__init__( )
        super(
            ScanNet,
            self).__init__()

        self._output_size = output_size
        self._mode = mode

        self._load(root, mode)
        self._filter_scene(scenes)

        self._augmenter = Augmentation(output_size,
                                       degrees,
                                       flip_p,
                                       jitter_bcsh)

        self._output_trafo = output_trafo
        self._data_augmentation = data_augmentation
        self._data_augmentation_for_replay = data_augmentation_for_replay
        
        self.unique = False
        self.replay = replay
        # TODO
        #self._weights = pd.read_csv(f'cfg/dataset/ml-hypersim/test_dataset_pixelwise_weights.csv').to_numpy()[:,0]

    def __getitem__(self, index):
        """
        Returns
        -------
        img [torch.tensor]: CxHxW, torch.float
        label [torch.tensor]: HxW, torch.int64
        img_ori [torch.tensor]: CxHxW, torch.float
        replayed [torch.tensor]: 1 torch.float32 
        global_idx [int]: global_index in dataset
        """
        idx = -1
        replayed = torch.zeros( [1] )
        
        
        global_idx = self.global_to_local_idx[index]
        
        # Read Image and Label
        label = imageio.imread(self.label_pths[global_idx])
        
        #170 ms
        label = loop_translate(label,self.d) # 0 = invalid 40 max number 
        label = torch.from_numpy(label.astype(np.uint8)).type(
            torch.float32)[None, :, :]  # C H W
        
        img = imageio.imread(self.image_pths[global_idx])
        img = torch.from_numpy(img).type(
            torch.float32).permute(
            2, 0, 1)/255  # C H W range 0-1


        if (self._mode == 'train' and 
            ( ( self._data_augmentation and idx == -1) or 
              ( self._data_augmentation_for_replay and idx != -1) ) ):
            
            img, label = self._augmenter.apply(img, label)
        else:
            img, label = self._augmenter.apply(img, label, only_crop=True)

        # check if reject
        if (label != -1).sum() < 10:
            # reject this example
            idx = random.randint(0, len(self) - 1)
            if not self.unique:
                return self[idx]
            else:
                replayed[0] = -999
                
        img_ori = img.clone()
        if self._output_trafo is not None:
            img = self._output_trafo(img)

        label = label - 1  # I need to check this for ML HYPERSIM !!!!!
        
        print(label.max(), label.min())
        return img, label.type(torch.int64)[0, :, :], img_ori, replayed.type(torch.float32), global_idx

    def __len__(self):
        return self.length

    def __str__(self):
        string = "="*90
        string += "\nML-HyperSim Dataset: \n"
        l = len(self)
        string += f"    Total Samples: {l}"
        string += f"  »  Mode: {self._mode} \n"
        string += f"    Replay: {self.replay}"
        string += f"  »  DataAug: {self._data_augmentation}"
        string += f"  »  DataAug Replay: {self._data_augmentation_for_replay}\n"
        string += "="*90
        return string
        
    def _load(self, root, mode, train_val_split=0.2):
        tsv = os.path.join(root, "scannetv2-labels.combined.tsv")
        df = pandas.read_csv(tsv, sep='\t')
        
        print( df.keys() )
        print( df["nyuClass"] )
        mapping_source = np.array( df['id'] ).tolist()
        mapping_target = np.array( df['nyu40id'] ).tolist()
        self.d = {mapping_source[i]:mapping_target[i] for i in range(len(mapping_target))}
        
        
        r = os.path.join( root,'scans')
        ls = [os.path.join(r,s[:9]) for s in os.listdir(r)]
        all_s = [os.path.join(r,s) for s in os.listdir(r)]

        scenes = np.unique( np.array(ls) ).tolist()
        sub_scene = {s: [ a[-3:] for a in all_s if a.find(s) != -1]  for s in scenes}
        for s in sub_scene.keys():
          sub_scene[s].sort()
        key = scenes[0] + sub_scene[scenes[0]][1] 

        self.image_pths = []
        self.label_pths = []
        self.train_test = []
        self.scenes = []
        for s in scenes:
          for sub in sub_scene[s]:
            print(s)
            colors = [str(p) for p in Path(s+sub).rglob('*color/*.jpg')]
            labels = [str(p) for p in Path(s+sub).rglob('*label-filt/*.png')]
            if len(colors) > 0:
              nr_train = int(  len(colors)* (1-train_val_split)  )
              nr_test = int( len(colors)-nr_train)
              print(nr_train, nr_test)
              self.train_test += ['train'] * nr_train
              self.train_test += ['test'] * nr_test
              self.scenes += [s.split('/')[-1]]*len(colors)
              self.image_pths += colors
              self.label_pths += labels
        
        self.valid_mode = np.array(self.train_test) == mode
        
        self.global_to_local_idx = np.arange( self.valid_mode.shape[0] )
        self.global_to_local_idx = (self.global_to_local_idx[self.valid_mode]).tolist()
        self.length = len(self.global_to_local_idx)
        
        print("Done")

    # @staticmethod
    # def get_classes():
    #     scenes = np.load('cfg/dataset/mlhypersim/scenes.npy').tolist()
    #     sceneTypes = sorted(set(scenes))
    #     return sceneTypes

    def _filter_scene(self, scenes):
        self.valid_scene = copy.deepcopy( self.valid_mode )
        if len(scenes) != 0:
          for sce in scenes:
            tmp = np.array(self.scenes) == sce
            self.valid_scene = np.logical_and(tmp. self.valid_scene )
            
        self.global_to_local_idx = np.arange( self.valid_mode.shape[0] )
        self.global_to_local_idx = (self.global_to_local_idx[self.valid_scene]).tolist()
        self.length = len(self.global_to_local_idx)

def test():
    # pytest -q -s src/datasets/ml_hypersim.py

    # Testing
    import imageio
    output_transform = tf.Compose([
        tf.Normalize([.485, .456, .406], [.229, .224, .225]),
    ])

    # create new dataset 
    dataset = ScanNet(
        mode='train',
        scenes=[],
        output_trafo=output_transform,
        output_size=400,
        degrees=10,
        flip_p=0.5,
        jitter_bcsh=[
            0.3,
            0.3,
            0.3,
            0.05],
        replay=True)
    
    dataset[0]
    dataloader = torch.utils.data.DataLoader(dataset,
                                             shuffle=False,
                                             num_workers=1,
                                             pin_memory=False,
                                             batch_size=2)
    
    import time
    st = time.time()
    print("Start")
    for j, data in enumerate(dataloader):
        t = data
        print(j)

    print('Total time', time.time()-st)
        #print(j)
        # img, label, _img_ori= dataset[i]    # C, H, W

        # label = np.uint8( label.numpy() * (255/float(label.max())))[:,:]
        # img = np.uint8( img.permute(1,2,0).numpy()*255 ) # H W C
        # imageio.imwrite(f'/home/jonfrey/tmp/{i}img.png', img)
        # imageio.imwrite(f'/home/jonfrey/tmp/{i}label.png', label)

if __name__ == "__main__":
    test()