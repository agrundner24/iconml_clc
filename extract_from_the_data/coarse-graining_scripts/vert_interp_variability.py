# For more documentation see vert_int_method_variability.ipynb

import os
import xarray as xr
import numpy as np

## Set by the user ##
GRID_RES = 'R02B05'      # Can be 'R02B05', 'R02B04'. Relevant for both the input and the output grid.
SOURCE = 'NARVAL'        # Can be 'NARVAL', 'QUBICC', 'HDCP2'. To set paths, input grids and variable names.
                         # For NARVAL additionally check var_path and output_path in lines 70-80s
VAR_TYPES = 'state_vars' # Can be 'state_vars', 'cloud_vars'. To focus on specific variables.
#####################

# Setting the paths, grids and variables
# -> ds_zh_lr: Low resolution vertical half levels
# -> ds_zh_hr: High resolution vertical half levels
if SOURCE == 'NARVAL':
    base_path = '/pf/b/b309170/my_work/NARVAL'
    # Variable name of half levels
    height_var = 'z_ifc'
    # Setting var_names (which variables to vertically interpolate)
    if VAR_TYPES == 'state_vars':
        var_names = ['qv', 'pres', 'rho', 'temp', 'u', 'v']
    elif VAR_TYPES == 'cloud_vars':
        var_names = ['clc', 'qi', 'qc']
    if GRID_RES == 'R02B05':
        ds_zh_lr = xr.open_dataset(os.path.join(base_path, 'grid_extpar/zghalf_icon-a_capped_R02B05.nc'))
        ds_zh_hr = xr.open_dataset(os.path.join(base_path, 'grid_extpar/z_ifc_R02B05_NARVAL_fg_DOM01_ML_capped.nc'))
    elif GRID_RES == 'R02B04':
        zg_lowres_path = os.path.join(narval_path, 'data_var_vertinterp/zg')
        zg_highres_path = os.path.join(narval_path, 'data/z_ifc')
        ds_zh_lr = xr.open_dataset(os.path.join(zg_lowres_path, 'zghalf_icon-a_capped.nc'))
        ds_zh_hr = xr.open_dataset(os.path.join(zg_highres_path, 'z_ifc_R02B04_NARVALI_fg_DOM01.nc')) 
elif SOURCE == 'QUBICC': 
    base_path = '/scratch/snx3000/agrundne' #Scratch
    # Variable name of half levels
    height_var = 'zghalf'
    # Setting var_names (which variables to vertically interpolate)
    if VAR_TYPES == 'state_vars':
        var_names = ['hus', 'pfull', 'rho', 'ta', 'ua', 'va']
    elif VAR_TYPES == 'cloud_vars':
        var_names = ['cl', 'cli', 'clw']
    # Setting ds_zh_lr and ds_zh_hr
    if GRID_RES == 'R02B05':
        ds_zh_lr = xr.open_dataset(os.path.join(base_path, 'grids/zghalf_icon-a_capped_R02B05.nc'))
        if VAR_TYPES == 'state_vars':
            ds_zh_hr = xr.open_dataset(os.path.join(base_path, 'grids/qubicc_l89_zghalf_ml_0019_R02B05_G.nc'))
        elif VAR_TYPES == 'cloud_vars':
            ds_zh_hr = xr.open_dataset(os.path.join(base_path, 'grids/qubicc_l91_zghalf_ml_0019_R02B05_G.nc'))
    elif GRID_RES == 'R02B04':
        ds_zh_lr = xr.open_dataset(os.path.join(base_path, 'grids/zghalf_icon-a_capped.nc'))
        ds_zh_hr = xr.open_dataset(os.path.join(base_path, 'grids/qubicc_l91_zghalf_ml_0015_R02B04_G.nc'))
elif SOURCE == 'HDCP2': # Actually I'm not working with HDCP2 data at the moment
    base_path = '/pf/b/b309170/bd1179_work/hdcp2' 
    # Variable name of half levels
    height_var = 'z_ifc'
    # Setting var_names (which variables to vertically interpolate)
    if VAR_TYPES == 'state_vars':
        var_names = ['hus', 'ninact', 'pres', 'qg', 'qh', 'qnc', 'qng', 'qnh', 'qni', 'qnr', 'qns', 'qr', 'qs', 'ta', 'ua', 'va', 'zg']
    elif VAR_TYPES == 'cloud_vars':
        var_names = ['clc', 'cli', 'clw']
    # Setting ds_zh_lr and ds_zh_hr
    assert GRID_RES == 'R02B04' # Not implemented for R02B05
    zghalf_highres_path = os.path.join(base_path, 'grids') # Need 151 vertical layers here, not 76 like in NARVAL.
    zghalf_lowres_path = os.path.join('/pf/b/b309170/my_work/NARVAL', 'data_var_vertinterp/zg') 
    ds_zh_hr = xr.open_dataset(os.path.join(zghalf_highres_path, 'z_ifc_vert_remapcon_3d_coarse_ll_DOM03_ML.nc'))
    ds_zh_lr = xr.open_dataset(os.path.join(zghalf_lowres_path, 'zghalf_icon-a_capped.nc'))
        
HORIZ_FIELDS = getattr(ds_zh_hr, height_var).values.shape[1]

# Actual vertical interpolation method
for var_name in var_names:
    print('Currently processing %s'%var_name)
    
    # Input and output folders
    if SOURCE == 'NARVAL':
        var_path = os.path.join('/pf/b/b309170/bd1179_work/narval/hcg_files', var_name)
        output_path = os.path.join('/pf/b/b309170/bd1179_work/narval/hvcg_files', var_name)
#         var_path = os.path.join(base_path, 'data', var_name) # Usually yes
#         output_path = os.path.join(base_path, 'data_var_vertinterp', var_name) # Usually yes
    elif SOURCE == 'QUBICC':
        var_path = os.path.join(base_path, 'hcg_data', var_name)
        output_path = os.path.join(base_path, 'hvcg_data', var_name)
    elif SOURCE == 'HDCP2':
        var_path = os.path.join(base_path, 'hor_cg_files_temp', var_name)
        output_path = os.path.join(base_path, 'data', var_name)
    
    # Can only happen in QUBICC
    if var_name == 'clw':
        var_name = 'qclw_phy'

    ls = os.listdir(var_path)

    for i in range(len(ls)):
        # Which file to load
        input_file = os.listdir(var_path)[i]        
        print(input_file)
        
        # Skip if the file is already in output_path
        if 'int_var_' + input_file in os.listdir(output_path):
            continue

        # Load files (ds_zh_lr = ds_zhalf_lowres)
        ds = xr.open_dataset(os.path.join(var_path, input_file))
        time_steps = len(ds.time)

        # Extract values
        var = getattr(ds, var_name).values
        zh_lr = ds_zh_lr.zghalf.values
        zh_hr = getattr(ds_zh_hr, height_var).values
        
        # Extract not-nan entries (var_n = var_notnan)
        not_nan = ~np.isnan(var[0,-1,:])   
        var_n = var[:,:,not_nan]
        zh_lr_n = zh_lr[:,not_nan]
        zh_hr_n = zh_hr[:,not_nan]

        # Modify the ndarray. Have 31 vertical full levels in the output. (var_out = var, vertically interpolated)
        var_out = np.full((time_steps, 31, var_n.shape[2]), np.nan) # var_n.shape[2] = Number of not_nans

        # Pretty fast implementation:
        for t in range(time_steps):
            for j in range(31):
                z_u = zh_lr_n[j, :]
                z_l = zh_lr_n[j+1, :]
                # weights.shape = var_n[0].shape = high-res_layers x len(not_nan)
                # len(z_u) = len(z_l) = len(not_nan)
                weights = np.maximum(np.minimum(z_u, zh_hr_n[:-1]) - np.maximum(zh_hr_n[1:], z_l), 0)
                var_out[t,j,:] = np.einsum('ij,ji->i', weights.T, var_n[t])/(z_u - z_l)
                

                # If the low-dim grid extends farther than the high-dim grid, we reinsert nans:
                should_be_nan = np.where(np.abs((z_u - z_l) - np.sum(weights, axis = 0)) >= 0.5)
                var_out[t,j,should_be_nan] = np.full(len(should_be_nan), np.nan)

        # Put it back in. Have 20480/81920 horizontal fields in the output.
        var_new = np.full((time_steps, 31, HORIZ_FIELDS), np.nan)
        var_new[:,:,not_nan] = var_out
        var_new_da = xr.DataArray(var_new, coords={'time':ds.time, 'lon':ds.clon, 'lat':ds.clat, 'height':ds.height[:31]}, dims=['time', 'height', 'cell'], name=var_name) 

        # Save it in a new file
        output_file = 'int_var_' + input_file
        var_new_da.to_netcdf(os.path.join(output_path, output_file))
