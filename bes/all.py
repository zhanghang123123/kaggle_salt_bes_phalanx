
import pandas as pd
import numpy as np
import os
import gc
from keras import backend as K
from keras.optimizers import RMSprop
from utils import ThreadsafeIter
from datasets.generators import SegmentationDataGenerator
from params import args
from callbacks.callbacks import get_callback
from augmentations import get_augmentations
from models.models import get_model
from losses import make_loss, Kaggle_IoU_Precision

#程序开始
def main():
  
    #读入数据，并存为列表，每一个item为列表中的一个元素
    train = pd.read_csv(args.folds_csv)
    #设置的模型保存路径
    MODEL_PATH = os.path.join(args.models_dir, args.network + args.alias)
    #将数据分折，原始输入数据就是预先分好折的，这个是存储的分折信息，12345列表元素
    folds = [int(f) for f in args.fold.split(',')]

    print('Training Model:', args.network + args.alias)

    for fold in folds:

        K.clear_session()
        print('***************************** FOLD {} *****************************'.format(fold))

        if fold == 0:
            if os.path.isdir(MODEL_PATH):
                raise ValueError('Such Model already exists')
            os.system("mkdir {}".format(MODEL_PATH))

        # Train/Validation sampling
        df_train = train[train.fold != fold].copy().reset_index(drop=True)
        df_valid = train[train.fold == fold].copy().reset_index(drop=True)

        # Train on pseudolabels only
        if args.pseudolabels_dir != '':
            pseudolabels = pd.read_csv(args.pseudolabels_csv)
            df_train = pseudolabels.sample(frac=1, random_state=13).reset_index(drop=True)

        # Keep only non-black images
        ids_train, ids_valid = df_train[df_train.unique_pixels > 1].id.values, df_valid[
            df_valid.unique_pixels > 1].id.values

        print('Training on {} samples'.format(ids_train.shape[0]))
        print('Validating on {} samples'.format(ids_valid.shape[0]))

        # Initialize model
        weights_path = os.path.join(MODEL_PATH, 'fold_{fold}.hdf5'.format(fold=fold))

        # Get the model
        model, preprocess = get_model(args.network,
                                      input_shape=(args.input_size, args.input_size, 3),
                                      freeze_encoder=args.freeze_encoder)

        # LB metric threshold
        def lb_metric(y_true, y_pred):
            return Kaggle_IoU_Precision(y_true, y_pred, threshold=0 if args.loss_function == 'lovasz' else 0.5)

        model.compile(optimizer=RMSprop(lr=args.learning_rate), loss=make_loss(args.loss_function),
                      metrics=[lb_metric])

        if args.pretrain_weights is None:
            print('No weights passed, training from scratch')
        else:
            wp = args.pretrain_weights.format(fold)
            print('Loading weights from {}'.format(wp))
            model.load_weights(wp, by_name=True)

        # Get augmentations
        augs = get_augmentations(args.augmentation_name, p=args.augmentation_prob)

        # Data generator
        dg = SegmentationDataGenerator(input_shape=(args.input_size, args.input_size),
                                       batch_size=args.batch_size,
                                       augs=augs,
                                       preprocess=preprocess)

        train_generator = dg.train_batch_generator(ids_train)
        validation_generator = dg.evaluation_batch_generator(ids_valid)

        # Get callbacks
        callbacks = get_callback(args.callback,
                                 weights_path=weights_path,
                                 fold=fold)

        # Fit the model with Generators:
        model.fit_generator(generator=ThreadsafeIter(train_generator),
                            steps_per_epoch=ids_train.shape[0] // args.batch_size * 2,
                            epochs=args.epochs,
                            callbacks=callbacks,
                            validation_data=ThreadsafeIter(validation_generator),
                            validation_steps=np.ceil(ids_valid.shape[0] / args.batch_size),
                            workers=args.num_workers)

        gc.collect()


if __name__ == '__main__':
    main()
