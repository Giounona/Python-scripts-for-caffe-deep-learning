# -*- coding: utf-8 -*-


#

#!/usr/bin/env python2
# 
# runfile('PATH/lmdb_from_mat.py', args='dbfold_balanced_HOG3 balanced_HOG.mat', wdir='PATH')
# this code takes as input the name of the folder that will contain the LMDB and the name of
# the .mat file that contains the data. The data should be organized in a 
# matrix num_images*width*hight*channels and a column matrix with labels.
# if this LMDB is used with nvidia DIGITS then the LMDB data should be imported 
# from NewDataset->other and the path for the corresponding folders should be given.
#
# for -v7.3 .mat files the data should be organised into width*hight*channels*num_images  
# and a raw matrix with labels.
#scipy.io.savemat('test.mat', dict(x=x, y=y))

"""
Functions for creating temporary LMDBs
Used in test_views
"""

import scipy.io
import argparse
#from collections import defaultdict
import os
import random
#import re
import sys
import time
import h5py
# Find the best implementation available
try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

import lmdb
import numpy as np
import PIL.Image

#if __name__ == '__main__':
   # dirname = os.path.dirname(os.path.realpath(__file__))
   # sys.path.insert(0, os.path.join(dirname,'..','..'))
   # from digits.config.load  import load_config
  #  load_config()

#from digits import utils

# Run load_config() first to set the path to Caffe
import caffe.io
from caffe.proto import caffe_pb2
#import caffe_pb2

IMAGE_SIZE  = 10
TRAIN_IMAGE_COUNT = 10000
VAL_IMAGE_COUNT = 1000
TEST_IMAGE_COUNT = 10
DB_BATCH_SIZE = 100


def create_lmdbs(folder, matfile, image_count=None, db_batch_size=None):
    """
    Creates LMDBs for generic inference
    Returns the filename for a test image

    Creates these files in "folder":
        train_images/
        train_labels/
        val_images/
        val_labels/
        mean.binaryproto
        test.png
    """

    if image_count is None:
        train_image_count = TRAIN_IMAGE_COUNT
    else:
        train_image_count = image_count
    val_image_count = VAL_IMAGE_COUNT

    if db_batch_size is None:
        db_batch_size = DB_BATCH_SIZE


# for -v7.3 .mat files
#    f = h5py.File(matfile)
#    x=f["labels"]
#    labels_hog=np.array(x)
#    x=f["data"] 
#    images_hog=np.array(x)
#    images_hog = images_hog.transpose((0,3,2,1))
    
    
    mat = scipy.io.loadmat(matfile)     
    images = mat['data'] 
    labels = mat['labels']   
# 
    
    print "Found %d image paths in image list" % len(labels)
    train_image_count=np.rint(len(labels)*0.8)
    val_image_count=len(labels)-train_image_count
    train_image_count=train_image_count.astype(int)
    val_image_count=val_image_count.astype(int)
    

    for phase, image_count in [
            ('train', train_image_count),
            ('val', val_image_count)]:

        print "Will create %d pairs of %s images" % (image_count, phase)

        # create DBs
        image_db = lmdb.open(os.path.join(folder, '%s_images' % phase),
                map_async=True,
                max_dbs=0)
        label_db = lmdb.open(os.path.join(folder, '%s_labels' % phase),
                map_async=True,
                max_dbs=0)

        # add up all images to later create mean image
        image_sum = None
        shape = None

        # arrays for image and label batch writing
        image_batch = []
        label_batch = []
        
        indecs=np.arange(0, len(labels)-1, 1)
        random.shuffle(indecs) 
        
        if phase=='train':
           x=indecs[0: train_image_count]          
        elif phase=='val':
           x=indecs[(train_image_count-1):len(labels)]
          
        for i in xrange(image_count):
            # pick up random indices from image list         
            index1 = x[i]
           
            label=labels[index1]
            
            if not shape:
               # initialize image sum for mean image
               image1=images[index1,:,:,:] 
               shape = image1.shape
               image_sum = np.zeros((3,shape[0],shape[1]), 'float64')
               #image_sum = np.zeros((6,shape[0],shape[1]), 'float64')


            # create BGR image: 
            image_pair = np.zeros(image_sum.shape)
            image1=images[index1,:,:,:]
            image2 = image1.transpose((2,1,0))
            image_pair[0:3] = image2
                       
            
            image_sum += image_pair

            # save test images on first pass
#            if label>0 and len(testImagesSameClass)<TEST_IMAGE_COUNT:
#                testImagesSameClass.append(image_pair)
#            if label==0 and len(testImagesDifferentClass)<TEST_IMAGE_COUNT:
#               Y testImagesDifferentClass.append(image_pair)

            # encode into Datum object
            image = image_pair
            datum = caffe.io.array_to_datum(image, -1)
            image_batch.append([str(i), datum])

            # create label Datum


            label= label[0]   
               
            label=label.astype(int)
            label_datum = caffe_pb2.Datum()
            label_datum.channels, label_datum.height, label_datum.width = 1, 1, 1
            label_datum.float_data.extend(np.array([label]).flat)
            label_batch.append([str(i), label_datum])

            if (i % db_batch_size == (db_batch_size - 1)) or (i == image_count - 1):
                _write_batch_to_lmdb(image_db, image_batch)
                _write_batch_to_lmdb(label_db, label_batch)
                image_batch = []
                label_batch = []

            if i % (image_count/20) == 0:
                print "%d/%d" % (i, image_count)

        # close databases
        image_db.close()
        label_db.close()

        # save mean
        mean_image = (image_sum / image_count).astype('uint8')
        _save_mean(mean_image, os.path.join(folder, '%s_mean.binaryproto' % phase))
        _save_mean(mean_image, os.path.join(folder, '%s_mean.png' % phase))

        # create test images
#        for idx, image in enumerate(testImagesSameClass):
#            _save_image(image, os.path.join(folder, '%s_test_same_class_%d.png' % (phase,idx)))
#        for idx, image in enumerate(testImagesDifferentClass):
#            _save_image(image, os.path.join(folder, '%s_test_different_class_%d.png' % (phase,idx)))

    return

def _write_batch_to_lmdb(db, batch):
    """
    Write a batch of (key,value) to db
    """
    try:
        with db.begin(write=True) as lmdb_txn:
            for key, datum in batch:
                lmdb_txn.put(key, datum.SerializeToString())
    except lmdb.MapFullError:
        # double the map_size
        curr_limit = db.info()['map_size']
        new_limit = curr_limit*2
        print('Doubling LMDB map size to %sMB ...' % (new_limit>>20,))
        try:
            db.set_mapsize(new_limit) # double it
        except AttributeError as e:
            version = tuple(int(x) for x in lmdb.__version__.split('.'))
            if version < (0,87):
                raise Error('py-lmdb is out of date (%s vs 0.87)' % lmdb.__version__)
            else:
                raise e
        # try again
        _write_batch_to_lmdb(db, batch)

def _save_image(image, filename):
    # converting from BGR to RGB
    image = image[[2,1,0],...] # channel swap
    # convert to (height, width, channels)
    image = image.astype('uint8').transpose((1,2,0))
    image = PIL.Image.fromarray(image)
    image.save(filename)

def _save_mean(mean, filename):
    """
    Saves mean to file

    Arguments:
    mean -- the mean as an np.ndarray
    filename -- the location to save the image
    """
    if filename.endswith('.binaryproto'):
        blob = caffe_pb2.BlobProto()
        blob.num = 1
        blob.channels = mean.shape[0]
        blob.height = mean.shape[1]
        blob.width = mean.shape[2]
        blob.data.extend(mean.astype(float).flat)
        with open(filename, 'wb') as outfile:
            outfile.write(blob.SerializeToString())

    elif filename.endswith(('.jpg', '.jpeg', '.png')):
        _save_image(mean, filename)
    else:
        raise ValueError('unrecognized file extension')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create-LMDB tool - DIGITS')

    ### Positional arguments

    parser.add_argument('folder',
            help='Where to save the images'
            )

    parser.add_argument('file_list',
            help='File list'
            )

    ### Optional arguments
    parser.add_argument('-c', '--image_count',
            type=int,
            help='How many images')

    args = vars(parser.parse_args())

    if os.path.exists(args['folder']):
        print 'ERROR: Folder already exists'
        sys.exit(1)
    else:
        os.makedirs(args['folder'])

    print 'Creating images at "%s" ...' % args['folder']

    start_time = time.time()

    create_lmdbs(args['folder'],
		 args['file_list'],
                 image_count=args['image_count'],
            )

    print 'Done after %s seconds' % (time.time() - start_time,)

