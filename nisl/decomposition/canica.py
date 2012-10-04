"""
CanICA
"""

# Author: ALexandre Abraham, Gael Varoquaux,
# License: BSD 3 clause
import copy

import numpy as np
from scipy import linalg, stats, ndimage

from sklearn.base import TransformerMixin
from sklearn.decomposition import fastica
from sklearn.externals.joblib import Memory
from sklearn.utils import check_random_state
from sklearn.utils.extmath import randomized_svd

from ..masking import extrapolate_out_mask
from ..base_model import BaseModel

def smooth_from_mask(data, mask, voxels, copy=True):
    """ Given a dataset n_voxels x n_sample, and a mask (n_x, n_y,
        n_z), smooth the dataset is real space.
    """
    if copy:
        data = data.copy()
    map3d = np.zeros(mask.shape)
    for this_map in data:
        map3d[mask] = this_map
        map3d, _ = extrapolate_out_mask(map3d, mask,
                                        iterations=np.ceil(voxels)+2)
        map3d = ndimage.gaussian_filter(map3d, voxels)
        this_map[:] = map3d[mask]
    return data



class CanICA(BaseModel, TransformerMixin):
    """Perform Canonical Independent Component Analysis.

    Parameters
    ----------
    data: array-like, shape = [[n_samples, n_features], ...]
        Training vector, where n_samples is the number of samples,
        n_features is the number of features. There is one vector per
        subject.

    n_components: int
        Number of components to extract

    mask: boolean array, optional
        Mask of the data.

    smooth: False or float, optional
        If smooth is not False, it gives the size, in voxel of the
        spatial smoothing to apply to the signal.

    random_state: int or RandomState
        Pseudo number generator state used for random sampling.

    Returns
    -------


    Notes
    -----


    """

    def __init__(self, n_components, threshold=1,
                memory=Memory(cachedir=None),
                mask=None, smooth=None,
                kurtosis_thr=False,
                maps_only=False,
                random_state=None):
       self.n_components = n_components
       self.threshold = threshold
       self.memory = memory
       self.mask = mask
       self.smooth = smooth
       self.kurtosis_thr = kurtosis_thr
       self.maps_only = maps_only
       self.random_state = random_state

    
    def fit(self, data, y):
        
        random_state = check_random_state(self.random_state)

        if hasattr(data, 'copy'):
            # It's an array
            data = data.copy()
        else:
            # Probably a list
            data = copy.deepcopy(data)
        pcas = list()
        # Do PCAs and CCAs
        for subject_data in data:
            subject_data -= subject_data.mean(axis=0)
            if self.smooth:
                assert self.mask is not None
                subject_data = self.memory.cache(smooth_from_mask)(subject_data,
                                    self.mask, self.smooth, copy=False)
                # Make the array writeable
                subject_data = np.asarray(subject_data).copy()
                subject_data -= subject_data.mean(axis=0)
            # PCA
            std = subject_data.std(axis=0)
            std[std==0] = 1
            subject_data /= std
            subject_data = subject_data.T
            subject_data = self.memory.cache(linalg.svd)(subject_data,
                                                        full_matrices=False)[0]
            subject_data = subject_data[:, :2 * self.n_components]
            pcas.append(subject_data)
            del subject_data

        if self.kurtosis_thr is False:
            kurtosis_thr = -np.inf
        else:
            kurtosis_thr = kurtosis_thr
        n_components = self.n_components
        while n_components < 3 * n_components:
            group_maps = self.memory.cache(randomized_svd)(np.concatenate(pcas, axis=1),
                                        n_components)[0]
            group_maps = group_maps[:, :n_components]

            ica_maps = self.memory.cache(fastica)(group_maps, whiten=False,
                                               fun='cube', random_state=random_state)[2]
            ica_maps = ica_maps.T
            kurtosis  = stats.kurtosis(ica_maps, axis=1)
            print 'kurtosis', kurtosis
            kurtosis_mask = kurtosis > kurtosis_thr
            if np.sum(kurtosis_mask) >= n_components:
                order = np.argsort(kurtosis)[::-1]
                ica_maps = ica_maps[order[:n_components]]
                break
            n_components += 1
                                                                                  
            del group_maps
        else:
            raise ValueError('Could not find components with high-enough'
            ' kurtosis')
        del pcas
        if not ica_maps.flags.writeable:
            ica_maps = np.asarray(ica_maps).copy()
        # Threshold
        ica_maps[np.abs(ica_maps) <
                 self.threshold/np.sqrt(ica_maps.shape[1])] = 0
        self.maps_ = ica_maps
        if not self.maps_only:
            # Relearn the time series
            self.learn_from_maps(data)

        return self

    def transform(self, X, y=None):
        """Apply un-mixing matrix "W" to X to recover the sources

            S = X * W.T
        """
        return np.dot(X, self.maps_.T)
