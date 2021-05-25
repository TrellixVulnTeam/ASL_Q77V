# TODO: Write a test and verify replaycallback always acts strictly contracting.

from pytorch_lightning.callbacks import Callback
from pytorch_lightning.utilities import rank_zero_warn
import torch

__all__ = ['VisuCallback']

class ReplayCallback(Callback):
  def __init__(self ):
    pass

  def on_epoch_start(self, trainer, pl_module):
    ls_global_indices = trainer.train_dataloader.dataset.datasets.get_replay_datasets_globals()
    bins_np, valid_np = pl_module._rssb.get() 

    for i,ls in enumerate(ls_global_indices):    
      elements = (bins_np[i][valid_np[i]]).tolist()
      # ensure to only allow contraction of the global indices within the dataset!
      for e in elements:
        assert e in ls
      ls_global_indices[i] = elements
    
    trainer.train_dataloader.dataset.datasets.set_replay_datasets_globals( ls_global_indices )

  def on_fit_end(self, trainer, pl_module):
    ls_global_indices = trainer.train_dataloader.dataset.datasets.get_datasets_globals()
    assert len(ls_global_indices) <= pl_module._rssb.bins.shape[0]
    
    # PERFORMS RANDOM MEMORY BUFFER FILLING
    for bin,ls in enumerate(ls_global_indices):
      el = pl_module._rssb.nr_elements

      torch_ls = torch.tensor( ls, dtype=torch.long)

      if el > len(ls):
        pl_module._rssb.bins[bin, :len(ls)] = torch_ls[ torch.range( 0, len(ls)-1, dtype=torch.long) ]
        pl_module._rssb.valid[bin, :len(ls)] = True
        pl_module._rssb.valid[bin, len(ls):] = False
      else:
        pl_module._rssb.bins[bin, :] = torch_ls[ torch.randperm( len(ls) )[:el] ] 
        pl_module._rssb.valid[bin, :] = True