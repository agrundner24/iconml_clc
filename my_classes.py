import numpy as np
import xarray as xr
import time
import os
from tensorflow import keras
from collections import OrderedDict

class TimeOut(keras.callbacks.Callback):
    '''
    Stop training after a batch when a certain time-limit (in minutes) is reached.
    Restoring the weights from the best concluded epoch.
    '''
    def __init__(self, t0, timeout):
        super().__init__()
        self.t0 = t0
        self.timeout = timeout  # time in minutes
        
    def on_train_begin(self, logs=None):
        self.best = np.Inf
        self.best_weights = self.model.get_weights()
        print("Starting training")
    
    def on_train_end(self, logs=None):
        print('Restore model weights from the end of the best epoch')
        self.model.set_weights(self.best_weights)
    
    # Note that training ends after a batch (not after a completed epoch)
    def on_train_batch_end(self, batch, logs=None):
        if time.time() - self.t0 > self.timeout * 60:  
            print(f"\nReached {(time.time() - self.t0) / 60:.3f} minutes of training, stopping")
            self.model.stop_training = True
            
    def on_epoch_end(self, epoch, logs=None):
        current = logs.get("val_loss")
        try:
            # Save the best weights if the validation loss has improved
            if np.less(current, self.best):
                self.best = current
                self.best_weights = self.model.get_weights()
        except:
            print('\nTraining is finished or no validation set was provided.')
            
def simple_sundqvist_scheme_rh(r, p, ps=101325):
    '''
        As a function of relative humidity [0, 1] and pressure [Pa]
        Furthermore ps is surface pressure (on average 101325 Pa)
        Output is cloud cover in [0, 1]
    '''
    rsat = 1
    r0_top = 0.8
    r0_surf = 0.968
    n = 2
    r0 = r0_top + (r0_surf - r0_top)*np.exp(1-(ps/p)**n)
    
    c = 0
    if r > r0:
        # r can actually slightly exceed 1 
        c = 1 - np.sqrt((np.minimum(r, 1) - rsat)/(r0 - rsat))
    return c

def simple_sundqvist_scheme(qv, T, p, ps=101325):
    '''
        As a function of specific humidity [kg/kg], temperature [K] and pressure [Pa]
        Furthermore ps is surface pressure (on average 101325 Pa)
        Output is cloud cover in [0, 1]
    '''
    # Computing relative humidity r 
    # (https://earthscience.stackexchange.com/questions/2360/how-do-i-convert-specific-humidity-to-relative-humidity)
    T0 = 273.15
    r = 0.00263*p*qv*np.exp((17.67*(T-T0))/(T-29.65))**(-1)
    
    return simple_sundqvist_scheme_rh(r, p, ps)

def write_infofile(file, input_and_output_vars, input_vars, model_path, output_path, NUM):
    '''
    Writes a bunch of information concerning the model and data into file
    It even copies the scaler parameters from a previously written file model_path/scaler.txt
    '''
    # How to use the model
    file.write('How to use the model:\n')
    file.write('model = tensorflow.keras.models.load_model(filename+\'.h5\')\n')
    file.write('model.predict(scaled input data)\n\n')
    # What kind of input/output variables are expected
    file.write('Input/Output\n')
    file.write('------------\n')
    file.write('Input and output variables:\n')
    file.write(input_and_output_vars)
    file.write('\nThe (order of) input variables:\n')
    file.write(input_vars)
    # Scaling
    file.write('\n\nScaling\n')
    file.write('-------\n')
    with open(os.path.join(model_path, 'scaler_%d.txt'%NUM), 'r') as scaler_file:
        [file.write(line) for line in scaler_file.readlines()]
    file.write('\n=> Apply this standard scaling to (only) the input data before processing.\n\n')
    # Preprocessed data
    file.write('Preprocessed data\n')
    file.write('-----------------\n')
    file.write(output_path + '/cloud_cover_input_train_%d.npy\n'%NUM)
    file.write(output_path + '/cloud_cover_input_valid_%d.npy\n'%NUM)
    file.write(output_path + '/cloud_cover_output_train_%d.npy\n'%NUM)
    file.write(output_path + '/cloud_cover_output_valid_%d.npy\n'%NUM)
    file.write(output_path + '/cloud_cover_input_test_%d.npy\n'%NUM)
    file.write(output_path + '/cloud_cover_output_test_%d.npy\n\n'%NUM)
    # Model performance
    file.write('Model\n')
    file.write('-----\n')
    
def read_mean_and_std(file_path):
    '''
    Reads the text-file provided by file_path. From it, we extract the means and the standard deviations of the features.
    Those were saved during the preprocessing step, when the training data was standardized.
    '''
    mean = []
    std = []
    with open(file_path) as file:
        lines = file.readlines()
        for i in range(len(lines)):
            if lines[i].startswith('Standard Scaler mean values') or lines[i].startswith('The mean values'):
                start_mean = i+1
            if lines[i].startswith('Standard Scaler standard deviation') or lines[i].startswith('The standard deviation'):
                end_mean = i-1
                start_std = i+1
            if lines[i].startswith('=> Apply this standard'):
                end_std = i-1    
                
        # Extract the mean as an array
        for k in range(start_mean, end_mean+1):
            offset = 0
            a = lines[k]
            if a.split(' ')[0] == '':
                b = np.zeros((len(a.split(' ')) - 1))
                offset = 1
            else:
                b = np.zeros((len(a.split(' '))))
            for j in range(len(a.split(' '))):
                if a.split(' ')[j] != '':
                    b[j-offset] = a.split(' ')[j].translate({ord(i): None for i in '[]'})
            mean = np.concatenate((mean, b))

        # Extract the standard deviation as an array
        for k in range(start_std, end_std+1):
            offset = 0
            a = lines[k]
            if a.split(' ')[0] == '':
                b = np.zeros((len(a.split(' ')) - 1))
                offset = 1
            else:
                b = np.zeros((len(a.split(' '))))
            for j in range(len(a.split(' '))):
                if a.split(' ')[j] != '':
                    b[j-offset] = a.split(' ')[j].translate({ord(i): None for i in '[]'})
            std = np.concatenate((std, b))
    return mean, std
    
def load_data(source, days, vert_interp=True, resolution='R02B04', order_of_vars=None):
    '''
        Loads data from the NARVAL or QUBICC experiment and stores it in a dictionary.
        
        source:        narval, qubicc
        days:          all, august, dec_1st, nov_2nd, nov_20s, all_hcs
        vert_interp:   Whether the data is vertically interpolated. Only needs to be specified for NARVAL with 'R02B04'
        resolution:    'R02B04' or 'R02B05'
        order_of_vars: If provided, the returned dictionary will have the variables in the specified order.
                       The cheaper variables (zg, coriolis, fr_lake, fr_land) are always loaded and discarded later.
                       For QUBICC 'clw' is also always initially loaded.
                       The more expensive variables (temp, pres, ...) are only loaded if they are included in order_of_vars
        
        returns: A dictionary containing the data with the features as keys.
    '''
    data_dict = OrderedDict()
    
    ############
    ## NARVAL ##
    ############
    # R02B04 yields default (order of) variables: 
    # ['qv', 'qc', 'qi', 'temp', 'pres', 'rho', 'zg'/'zf', 'Coriolis', 'fr_lake', 'fr_land', ('fr_seaice', ) 'clc', 'cl_area']
    # R02B05 yields default (order of) variables:
    # ['qv', 'qc', 'qi', 'temp', 'pres', 'rho', 'u', 'v', 'zg', 'coriolis', 'fr_lake', 'fr_land', 'clc', 'cl_area']
    if source == 'narval':
        if vert_interp == True and resolution == 'R02B04':
            path = '/pf/b/b309170/my_work/NARVAL/data_var_vertinterp/'
#             surface_nearest_layer = 30
            file_name_prefix = 'int_var_'
            height_variable_name = 'zg'
            height_file_location = 'zg/zg_icon-a_capped.nc'
        elif vert_interp == False and resolution == 'R02B04':
            path = '/pf/b/b309170/my_work/NARVAL/data/'
#             surface_nearest_layer = 74
            file_name_prefix = ''
            height_variable_name = 'zf'
            height_file_location = 'z_ifc/zf_R02B04_NARVALI_fg_DOM01.nc'
        elif resolution == 'R02B05':
            path = '/pf/b/b309170/my_work/NARVAL/data_var_vertinterp_R02B05/'
            file_name_prefix = 'int_var_'
            height_variable_name = 'zg'
            height_file_location = 'zg/zg_icon-a_capped.nc'
            
        # Grid path and name for the Coriolis Parameter
        grid_path = '/pf/b/b309170/my_work/NARVAL/grid_extpar'
        if resolution == 'R02B04':
            grid_name = 'icon_grid_0005_R02B04_G.nc'
        elif resolution == 'R02B05':
            grid_name = 'icon_grid_0019_R02B05_G.nc'
            
        # Get not_nan quickly 
        DS = xr.open_dataset(path+'clc/'+file_name_prefix+'clc_'+resolution+'_NARVALI_2013123100_cloud_DOM01_0034.nc')
        da = DS.clc.values
        not_nan = ~np.isnan(da[0,-1,:]) #The surface-nearest layer shall not contain NAN-values

        # Which days should we load
        if days=='all':
            load_days = '_'+resolution+'_*'
        elif days=='august':
            load_days = '_'+resolution+'_NARVALII_201608*'
        elif days=='dec_1st':
            load_days = '_'+resolution+'_NARVALI_2013120100'
        else:
            raise ValueError('The entered days are invalid.')
            
        ## Hourly data
        #3D input
        if resolution=='R02B04':
            vars = ['qv', 'qc', 'qi', 'temp', 'pres', 'rho']
        elif resolution=='R02B05':
            vars = ['qv', 'qc', 'qi', 'temp', 'pres', 'rho', 'u', 'v']
        for i in range(len(vars)):
            if vars[i] in order_of_vars:
                print(vars[i])
                DS = xr.open_mfdataset(path+vars[i]+'/'+file_name_prefix+vars[i]+load_days+'_fg_DOM01_00*.nc', combine='by_coords')
                da = getattr(DS, vars[i]).values
                if resolution=='R02B05' and days=='all':
                    data_dict[vars[i]] = np.delete(da[:,:,not_nan], 1651, axis=0) #There's a problem with int_var_*_R02B05_NARVALII_2016082900_fg_DOM01_0016.nc.
                elif resolution=='R02B05' and days=='august':
                    raise ValueError('Please implement the exclusion of int_var_*_R02B05_NARVALII_2016082900_fg_DOM01_0016.nc first!')
                else:
                    data_dict[vars[i]] = da[:,:,not_nan]
                

        ## Time-invariant input
        #zg/zf
        DS = xr.open_dataset(path+height_file_location)
        da = getattr(DS, height_variable_name).values
        data_dict[height_variable_name] = da[:,not_nan]
        
        #Coriolis Parameter
        DS = xr.open_dataset(os.path.join(grid_path, grid_name))
        lat_cell_center = DS.lat_cell_centre.values
        # Rotation rate of the earth
        Omega = 7.2921*10**(-5) # in 1/s
        # Varies between -0.0001458 and 0.0001458
        data_dict['coriolis'] = (2*Omega*np.sin(lat_cell_center))[not_nan]
        
        #fr_lake
        DS = xr.open_dataset(path+'../grid_extpar/fr_lake_'+resolution+'_NARVAL_fg_DOM01.nc')
        da = DS.FR_LAKE.values
        data_dict['fr_lake'] = da[not_nan]
        
        #fr_land
        DS = xr.open_dataset(path+'../grid_extpar/fr_land_'+resolution+'_NARVAL_fg_DOM01.nc')
        da = DS.fr_land.values
        data_dict['fr_land'] = da[not_nan] 
        
        if vert_interp == False:
            #fr_seaice
            DS = xr.open_mfdataset(path+'fr_seaice/fr_seaice'+load_days+'_fg_DOM01_00*.nc', combine='by_coords')
            da = DS.fr_seaice.values
            data_dict['fr_seaice'] = da[:, not_nan]
           
        ## Output
        #clc, cl_area
        vars = ['clc', 'cl_area']
        for i in range(len(vars)):
            DS = xr.open_mfdataset(path+vars[i]+'/'+file_name_prefix+vars[i]+load_days+'_cloud_DOM01_00*.nc', 
                                   combine='by_coords')
            if vars[i] == 'cl_area':
                da = getattr(DS, 'clc').values
            else:
                da = getattr(DS, vars[i]).values            
            if resolution=='R02B05' and days=='all':
                data_dict[vars[i]] = np.delete(da[:,:,not_nan], 1651, axis=0) #There's a problem with int_var_*_R02B05_NARVALII_2016082900_fg_DOM01_0016.nc.
            elif resolution=='R02B05' and days=='august':
                raise ValueError('Please implement the exclusion of int_var_*_R02B05_NARVALII_2016082900_fg_DOM01_0016.nc first!')
            else:
                data_dict[vars[i]] = da[:,:,not_nan]
    
    ############
    ## QUBICC ##
    ############
    # Yields default (order of) variables: 
    # R2B4: ['zg', 'coriolis', 'fr_lake', 'fr_seaice', 'fr_land', 'hus', 'qclw_phy', 'cli', 'ta', 'pfull', 'rho', 'cl', 'cl_area']
    # R2B5: ['zg', 'coriolis', 'fr_lake', 'fr_land', 'hus', 'qclw_phy', 'cli', 'ta', 'pfull', 'rho', 'ua', 'va', 'cl', 'cl_area']
    if source == 'qubicc':
        
        if resolution == 'R02B04':
            path = '/pf/b/b309170/my_work/QUBICC/data_var_vertinterp/'
#             surface_nearest_layer = 74
#             file_name_prefix = ''
            height_filename = 'zg_icon-a_capped.nc'
        elif resolution == 'R02B05':
            path = '/pf/b/b309170/my_work/QUBICC/data_var_vertinterp_R02B05/'
#             file_name_prefix = 'int_var_'
            height_filename = 'zg_icon-a_capped_R02B05.nc'
    
        # Grid path and name for the Coriolis Parameter
        grid_path = '/pf/b/b309170/my_work/QUBICC/grids'
        if resolution == 'R02B04':
            grid_name = 'icon_grid_0013_R02B04_G.nc'
        elif resolution == 'R02B05':
            grid_name = 'icon_grid_0019_R02B05_G.nc'        
        
        # Get not_nan quickly
        DS = xr.open_mfdataset(path+'cl/int_var_hc2_02_p1m_cl_ml_20041107T100000Z_'+resolution+'.nc', combine='by_coords')
        da = DS.cl.values
        not_nan = ~np.isnan(da[0,30,:]) #The surface-nearest layer 30 shall not contain NAN-values

        ## Time-invariant input
        #zg
        DS = xr.open_dataset('/pf/b/b309170/my_work/QUBICC/grids/'+height_filename)
        da = DS.zg.values
        #not_nan = ~np.isnan(da[0,:])
        data_dict['zg'] = da[:,not_nan]
        
        #Coriolis Parameter
        DS = xr.open_dataset(os.path.join(grid_path, grid_name))
        lat_cell_center = DS.lat_cell_centre.values
        # Rotation rate of the earth
        Omega = 7.2921*10**(-5) # in 1/s
        # Varies between -0.0001458 and 0.0001458
        data_dict['coriolis'] = (2*Omega*np.sin(lat_cell_center))[not_nan]

        #fr_lake
        DS = xr.open_dataset(path+'fr_lake/fr_lake_'+resolution+'.nc')
        da = DS.lake.values
        data_dict['fr_lake'] = da[not_nan]
        
        if resolution == 'R02B04':
            #fr_seaice
            DS = xr.open_dataset(path+'fr_seaice/fr_seaice_'+resolution+'.nc')
            da = DS.siconcbcs.values
            data_dict['fr_seaice'] = da[0, not_nan]

        #fr_land
        DS = xr.open_dataset(path+'fr_land/fr_land_'+resolution+'.nc')
        da = DS.land.values
        data_dict['fr_land'] = da[not_nan] 
        
        # Which days should we load
        if days=='all':
            load_days = '20041*.nc'
        elif days=='nov_20s':
            load_days = '2004112*.nc'
        elif days=='nov_2nd':
            load_days = '20041102*.nc'
        elif days=='all_hcs':
            load_days = '*.nc'
        else:
            raise ValueError('The entered days are invalid.')
        
        ## Hourly data
        #3D data: All possible input variables
        vars = ['hus', 'clw', 'cli', 'ta', 'pfull', 'rho', 'ua', 'va', 'cl', 'cl_area']
        for i in range(len(vars)):
            if vars[i] in order_of_vars:
                print(vars[i])
                DS = xr.open_mfdataset(path+vars[i]+'/int_var_*_02_p1m_'+vars[i]+'_ml_'+load_days, combine='by_coords')
                # There may be a difference between the filename and the actual variable name
                if vars[i] == 'clw':
                    da = getattr(DS, 'qclw_phy').values
                elif vars[i] == 'cl_area':
                    da = getattr(DS, 'cl').values  
                else:
                    da = getattr(DS, vars[i]).values  
                if resolution=='R02B05' and days=='all_hcs':
                    data_dict[vars[i]] = np.delete(da[:,:,not_nan], 434, axis=0) #There's a problem with int_var_hc2_02_p1m_ta_ml_20041119T020000Z_R02B05.nc.
                else:
                    data_dict[vars[i]] = da[:,:,not_nan]
    
    # Correct the order (possibly also removing one or two 2D features)
    if order_of_vars != None:
        for key in order_of_vars:
            data_dict = OrderedDict((k, data_dict[k]) for k in order_of_vars)
    
    return data_dict


def load_all_data(days, order_of_vars=None):
    '''
        Loads more data from NARVAL and stores it in a dictionary.
        Actually I'm not sure whether I actually use load_all_data anywhere.
        
        days:          all, august, dec_1st
        order_of_vars: If provided, the returned dictionary will have the variables in the specified order.
        
        returns: A dictionary containing the data with the features as keys.
    '''
    data_dict = OrderedDict()
    
    # Yields default (order of) variables: 
    # ['qv', 'qc', 'qi', 'temp', 'pres', 'rho', 'u', 'v', 'zf', 'fr_lake', 'fr_land', 'clc']
    
    path = '/pf/b/b309170/my_work/NARVAL/data/'
#     surface_nearest_layer = 74
    file_name_prefix = ''
    height_variable_name = 'zf'
    height_file_location = 'z_ifc/zf_R02B04_NARVALI_fg_DOM01.nc'

    # Get not_nan quickly
    DS = xr.open_dataset(path+'clc/'+file_name_prefix+'clc_R02B04_NARVALI_2013123100_cloud_DOM01_0034.nc')
    da = DS.clc.values
    not_nan = ~np.isnan(da[0,-1,:]) #The surface-nearest layer shall not contain NAN-values

    # Which days should we load
    if days=='all':
        load_days = '_R02B04_*'
    elif days=='august':
        load_days = '_R02B04_NARVALII_201608*'
    elif days=='dec_1st':
        load_days = '_R02B04_NARVALI_2013120100'
    else:
        raise ValueError('The entered days are invalid.')

    ## Hourly data
    #3D input
    vars = ['qv', 'qc', 'qi', 'temp', 'pres', 'rho', 'u', 'v']
    for i in range(len(vars)):
        DS = xr.open_mfdataset(path+vars[i]+'/'+file_name_prefix+vars[i]+load_days+'_fg_DOM01_00*.nc', combine='by_coords')
        da = getattr(DS, vars[i]).values
        data_dict[vars[i]] = da[:,:,not_nan]

    ## Time-invariant input
    #zf
    DS = xr.open_dataset(path+height_file_location)
    da = getattr(DS, height_variable_name).values
    data_dict[height_variable_name] = da[:,not_nan]

    #fr_lake
    DS = xr.open_dataset(path+'../grid_extpar/fr_lake_R02B04_NARVAL_fg_DOM01.nc')
    da = DS.FR_LAKE.values
    data_dict['fr_lake'] = da[not_nan]

    #fr_land
    DS = xr.open_dataset(path+'../grid_extpar/fr_land_R02B04_NARVAL_fg_DOM01.nc')
    da = DS.fr_land.values
    data_dict['fr_land'] = da[not_nan] 

    ## Output
    #clc
    vars = ['clc']
    for i in range(len(vars)):
        DS = xr.open_mfdataset(path+vars[i]+'/'+file_name_prefix+vars[i]+load_days+'_cloud_DOM01_00*.nc', 
                               combine='by_coords')
        da = getattr(DS, vars[i]).values
        data_dict[vars[i]] = da[:,:,not_nan]

    # Correct the order (possibly also removing one or two features)
    if order_of_vars != None:
        for key in order_of_vars:
            data_dict = OrderedDict((k, data_dict[k]) for k in order_of_vars)
    
    return data_dict

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
