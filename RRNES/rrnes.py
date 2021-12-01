# -*- coding: utf-8 -*-
"""
Created on Sun Jun 21 21:54:32 2020

@author: kangsun
"""
import h5py
import numpy as np
import datetime as dt
from dateutil.relativedelta import relativedelta
import logging
import os
import pandas as pd
from scipy.io import loadmat

def F_delta_omega(inp,Q,tau):
    """
    forward model for F_fit_ime_C
    """
    A = inp['A']
    L = inp['L']
    ws = inp['ws']
    f = inp['f']
    if 'Omega_bg' not in inp.keys():
        return Q/(A*(ws/L/f+1/tau))
    else:
        return (Q+inp['Omega_bg']*ws*A/f/L)/(A*(ws/L/f+1/tau))

def F_forward(inp,Q,tau):
    """
    forward model for F_GaussNewton_OE
    """
    A = inp['A']
    L = inp['L']
    ws = inp['ws']
    f = inp['f']
    if 'Omega_bg' not in inp.keys():
        y = Q/(A*(ws/L/f+1/tau))
        dydQ = 1/(A*(ws/L/f+1/tau))
        dydtau = Q/A*1/(ws/L/f+1/tau)**2*1/tau**2
        return y, dydQ, dydtau
    else:
        y = (Q+inp['Omega_bg']*ws*A/f/L)/(A*(ws/L/f+1/tau))
        dydQ = 1/(A*(ws/L/f+1/tau))
        dydtau = (Q+inp['Omega_bg']*ws*A/f/L)/A*1/(ws/L/f+1/tau)**2*1/tau**2
        return y, dydQ, dydtau

def F_forward12(inp,Q_array,tau_array):
    """
    forward model for multiple month ime
    """
    A = inp['A']
    L = inp['L']
    xx = inp['xx']
    f = inp['f']
    nx_per_month = inp['nx_per_month']
    index_array = np.cumsum(nx_per_month)
    nmonth = len(nx_per_month)
    yhat = np.full(xx.shape,np.nan)
    dydQ = np.zeros((len(xx),nmonth))
    dydtau = np.zeros((len(xx),nmonth))
    for i in range(nmonth):
        if i == 0:
            ind1 = 0 
        else:
            ind1 = int(index_array[i-1])
        ind2 = int(index_array[i])
        yhat[ind1:ind2] = Q_array[i]/(A*(xx[ind1:ind2]/L/f+1/tau_array[i]))
        dydQ[ind1:ind2,i] = 1/(A*(xx[ind1:ind2]/L/f+1/tau_array[i]))
        dydtau[ind1:ind2,i] = Q_array[i]/A*1/(xx[ind1:ind2]/L/f+1/tau_array[i])**2*1/tau_array[i]**2
    return yhat, dydQ, dydtau

def F_month_corr(m1,m2,dm):
    # error correlation between two months
    return np.exp(-np.min([np.abs(m1-m2),12-np.abs(m1-m2)])/dm)

class IME():
    """
    place holder for output object of F_fit_ime_C
    """
    pass

class IMEOE():
    """
    place holder for output object of F_GaussNewton_OE
    """
    pass

class RRNES(object):
    def __init__(self,whichBasin,whichSatellite,
                 dateArray,dataDir,
                 moleculeList=['NO2'],
                 basin_boundary_path=None,
                 inventoryPathList=[]):
        """
        whichBain:
            'po', 'jh', or 'so'
        whichSatellite:
            'TROPOMI' or 'OMI'
        dateArray:
            a numpy array of datetime.date objects, where year/month are used to identify which month(s) to load
        dataDir:
            directory of h5 files generated by S_save_basin_wind_aggregation.m
        basin_boundary_path:
            path to the basin boundary mat file
        inventoryPathList:
            not useful anymore
        """
        self.logger = logging.getLogger(__name__)
        self.logger.info('creating an instance of MonthlyIME')
        self.whichBasin = whichBasin
        self.whichSatellite = whichSatellite
        self.dateArray = dateArray
        self.dataDir = dataDir
        self.moleculeList = moleculeList
        if len(moleculeList) > 1:
            self.logger.error('Only one molecule is supported per instance!')
        molecularWeightList = []
        for mol in moleculeList:
            if mol == 'NO2':
                molecular_weight = 0.046
            elif mol == 'NH3':
                molecular_weight = 0.017
            else:
                molecular_weight = None
            molecularWeightList.append(molecular_weight)
        self.molecularWeightList = molecularWeightList
        if basin_boundary_path is not None:
            self.logger.info('loading basin boundary file '+basin_boundary_path)
            d = loadmat(basin_boundary_path,squeeze_me=True)
            self.b1x = d['b1x']
            self.b1y = d['b1y']
            self.L = d['L']
            self.minlat1 = d['minlat1']
            self.maxlat1 = d['maxlat1']
            self.minlon1 = d['minlon1']
            self.maxlon1 = d['maxlon1']
            self.minlat2 = d['minlat2']
            self.maxlat2 = d['maxlat2']
            self.minlon2 = d['minlon2']
            self.maxlon2 = d['maxlon2']
        if len(inventoryPathList) > 0:
            if len(inventoryPathList) != len(moleculeList):
                self.logger.error('length of molecules have to be the same as length of inventory')
            self.logger.info('loading monthly emission estimates')
            self.inventories = {}
            for (i,molecule) in enumerate(moleculeList):
                T = pd.read_csv(inventoryPathList[i],index_col=0) # mol/s
                self.inventories[molecule] = np.array([T.loc[d.year].iloc[d.month-1] for d in dateArray])
    
    def F_load_jpl(self,jpl_path,jpl_type='tot'):
        '''
        recover lost function that did not commit, 2021/10/02
        jpl files: https://tes.jpl.nasa.gov/tes/chemical-reanalysis/products/monthly-mean
        '''
        from netCDF4 import Dataset
        from shapely.geometry import Polygon
        import glob
        jpl_flist = glob.glob(os.path.join(jpl_path,'mon_emi_nox_'+jpl_type+'_20*.nc'))
        jpl_dates = []
        for (i,fn) in enumerate(jpl_flist):
            jpl_year = int(fn[-7:-3])
            nc = Dataset(fn)
            jpl_dates = jpl_dates+[dt.date(jpl_year,int(m+1),15) for m in nc['time'][:]]
            if i == 0:
                jpl_lon = nc['lon'][:]
                jpl_lon[jpl_lon>=180] = jpl_lon[jpl_lon>=180]-360#jpl lon is 0-360
                jpl_lat = nc['lat'][:]
                lon_int = (jpl_lon>self.minlon2) & (jpl_lon<self.maxlon2)
                lat_int = (jpl_lat>self.minlat2) & (jpl_lat<self.maxlat2)
                jpl_lon = jpl_lon[lon_int]
                jpl_lat = jpl_lat[lat_int]
                jpl_nox = np.array([nox_map[np.ix_(lat_int,lon_int)] for nox_map in nc['nox'][:]])
            else:
                jpl_nox = np.concatenate((jpl_nox,
                                         np.array([nox_map[np.ix_(lat_int,lon_int)] for nox_map in nc['nox'][:]])),
                                         axis=0)
        jpl_dates = np.array(jpl_dates)
        time_mask = np.array([(d>=np.min(self.dateArray)) &(d<=np.max(self.dateArray)) for d in jpl_dates])
        jpl_dates = jpl_dates[time_mask]
        jpl_nox = jpl_nox[time_mask,]/0.014#kgN/m2/s to mol/m2/s            
        w = np.zeros((len(jpl_lat),len(jpl_lon)))
        lon_grid_size = np.median(np.abs(np.diff(jpl_lon)))
        lat_grid_size = np.median(np.abs(np.diff(jpl_lat)))
        ppolygon = Polygon(np.vstack((self.b1x,self.b1y)).T)
        verts = []
        for ilat in range(len(jpl_lat)):
            for ilon in range(len(jpl_lon)):
                gx = [jpl_lon[ilon]-lon_grid_size/2,jpl_lon[ilon]-lon_grid_size/2,jpl_lon[ilon]+lon_grid_size/2,jpl_lon[ilon]+lon_grid_size/2]
                gy = [jpl_lat[ilat]-lat_grid_size/2,jpl_lat[ilat]+lat_grid_size/2,jpl_lat[ilat]+lat_grid_size/2,jpl_lat[ilat]-lat_grid_size/2]
                verts.append(np.array([gx,gy]).T)
                gpolygon = Polygon(np.vstack((gx,gy)).T)
                w[ilat,ilon] = ppolygon.intersection(gpolygon).area/(lon_grid_size*lat_grid_size)
        jpl_emissionRate = np.zeros(len(jpl_dates))
        for i in range(len(jpl_dates)):
            jpl_emissionRate[i]=np.nansum(jpl_nox[i,...]*w)/np.sum(w)*np.power(self.L,2)#mol m-2 s-1 to mol s-1
        nc.close()
        jpl = {}
        jpl['dates'] = jpl_dates
        jpl['lon'] = jpl_lon
        jpl['lat'] = jpl_lat
        jpl['map'] = jpl_nox
        jpl['emission_rate'] = jpl_emissionRate
        return jpl
    def F_load_carb(self,carb_path,season='summer',exclude_natural=True):
        '''
        load carb emission from https://www.arb.ca.gov/app/emsinv/fcemssumcat/fcemssumcat2016.php
        season can be summer, winter, or annual
        '''
        if season == 'summer':
            months = [6,7,8]
        elif season == 'winter':
            months = [1,2,12]
        elif season == 'annual':
            months = list(range(1,13))
        df = pd.read_csv(carb_path)
        if exclude_natural:
            df = df.loc[~df['CATEGORY'].isin(['NATURAL SOURCES'])]
        carb_year = []
        carb_data = []
        mw = self.molecularWeightList[0]
        for year in range(2000,2022):
            if str(year) in df.keys():
                carb_year.append(year)
                carb_data.append(np.nansum(df[str(year)])*1e3/mw/86400)
        carb_dates = np.array([])
        carb_emission_rate = np.array([])
        for (iyear,year) in enumerate(carb_year):
            year_dates = np.array([dt.date(year,m,15) for m in months])
            carb_dates = np.append(carb_dates,year_dates)
            carb_emission_rate = np.append(carb_emission_rate,np.repeat(carb_data[iyear],len(months)))
        carb = {}
        carb['dates'] = carb_dates
        carb['emission_rate'] = carb_emission_rate
        return carb
    
    def F_load_ceds(self,ceds_path):
        '''
        load ceds inventory, calcuate basin mean
        '''
        from netCDF4 import Dataset
        from shapely.geometry import Polygon
        nc = Dataset(ceds_path)
        dates = np.array([dt.date(1750,1,1)+dt.timedelta(days=d) for d in nc['time'][:]])
        time_mask = np.array([(d>=np.min(self.dateArray)) &(d<=np.max(self.dateArray)) for d in dates])
        dates = dates[time_mask]
        ceds_lon = nc['lon'][:]
        ceds_lat = nc['lat'][:]
        if 'NO2' in self.moleculeList:
            map_field = 'NOx_em_anthro'
        ceds_map = np.nansum(nc[map_field][:][time_mask,],axis=1)/0.046# kg m-2 s-1 to mol m-2 s-1
        lon_int = (ceds_lon>self.minlon2) & (ceds_lon<self.maxlon2)
        lat_int = (ceds_lat>self.minlat2) & (ceds_lat<self.maxlat2)
        ceds_lon = ceds_lon[lon_int]
        ceds_lat = ceds_lat[lat_int]
        ceds_map0 = np.full((len(dates),len(ceds_lat),len(ceds_lon)),np.nan)
        for i in range(len(dates)):
            ceds_map0[i,...] = ceds_map[i,...][np.ix_(lat_int,lon_int)]            
        w = np.zeros((len(ceds_lat),len(ceds_lon)))
        grid_size = np.median(np.abs(np.diff(ceds_lat)))
        ppolygon = Polygon(np.vstack((self.b1x,self.b1y)).T)
        verts = []
        for ilat in range(len(ceds_lat)):
            for ilon in range(len(ceds_lon)):
                gx = [ceds_lon[ilon]-grid_size/2,ceds_lon[ilon]-grid_size/2,ceds_lon[ilon]+grid_size/2,ceds_lon[ilon]+grid_size/2]
                gy = [ceds_lat[ilat]-grid_size/2,ceds_lat[ilat]+grid_size/2,ceds_lat[ilat]+grid_size/2,ceds_lat[ilat]-grid_size/2]
                verts.append(np.array([gx,gy]).T)
                gpolygon = Polygon(np.vstack((gx,gy)).T)
                w[ilat,ilon] = ppolygon.intersection(gpolygon).area/grid_size**2
        ceds_emissionRate = np.zeros(len(dates))
        for i in range(len(dates)):
            ceds_emissionRate[i]=np.nansum(ceds_map0[i,...]*w)/np.sum(w)*np.power(self.L,2)#mol m-2 s-1 to mol s-1
        nc.close()
        ceds = {}
        ceds['dates'] = dates
        ceds['lon'] = ceds_lon
        ceds['lat'] = ceds_lat
        ceds['map'] = ceds_map0
        ceds['emission_rate'] = ceds_emissionRate
        return ceds
    
    def F_load_monthly_h5(self,fileNameArray=[],fileIntegrationMonth=None):
        """
        load monthly data to a numpy array of dictionaries, each dict will be data for a month
        By default, no inputs are needed, as months are defined previously by
        self.dateArray
        fileNameArray:
            if provided, it should be a list of file names, e.g., ['TROPOMI_201805to201805.h5']
        fileIntegrationMonth:
            by default one, i.e., monthly. How many months are integrated in S_save_basin_wind_aggregation.m
        output:
            monthlyDictArray is an numpy array of dictionaries. each dictionary corresponds to one month by default
        """
        if not fileNameArray:
            self.logger.info('no file names are supplied, assuming standard file name format')
            if fileIntegrationMonth == None:
                fileNameArray = [os.path.join(self.dataDir,self.whichSatellite+'_'+
                                              Date.strftime('%Y%m')+'.h5') \
                                for Date in self.dateArray]
            else:    
                fileNameArray = [os.path.join(self.dataDir,self.whichSatellite+'_'+
                                              Date.strftime('%Y%m')+'to'+
                                              (Date+relativedelta(months=fileIntegrationMonth-1)).strftime('%Y%m')+'.h5') \
                                for Date in self.dateArray]
        self.fileNameArray = fileNameArray
        monthlyDictArray = np.empty((len(fileNameArray)),dtype=object)
        for ifile,fileName in enumerate(fileNameArray):
            m = {}
            if not os.path.exists(fileName):
                self.logger.warning(fileName+' does not exist! returning empty dict')
                monthlyDictArray[ifile] = {}
                continue
            self.logger.info('loading '+fileName)
            with h5py.File(fileName,mode='r') as f:
                for key in list(f['/'+self.whichBasin].keys()):
                    if key not in self.moleculeList:
                        m[key] = f['/'+self.whichBasin+'/'+key][...].squeeze()
                    else:
                        m[key] = {}
                        for k in list(f['/'+self.whichBasin+'/'+key].keys()):
                            m[key][k] = f['/'+self.whichBasin+'/'+key+'/'+k][...].squeeze()
                    
            monthlyDictArray[ifile] = m
        return monthlyDictArray
    
    def F_sum_IME_to_emission(self,monthlyDict,tau,ime_f=[],if_use_ws=True,wsRange=(0.,21.)):
        '''
        weight-sum the arrays in ime to emission
        tau:
            chemical lifetime in s
        '''
        U = monthlyDict[self.moleculeList[0]]['ime_ws']
        if len(ime_f)==0:
            ime_f = 2*np.ones(U.shape)
        elif len(ime_f)==1:
            ime_f = ime_f*np.ones(U.shape)
        mask = (U >= wsRange[0]) & (U <= wsRange[1])
        U = U[mask]
        ime_f = ime_f[mask]
        yData = monthlyDict[self.moleculeList[0]]['ime_C'][mask]
#        if self.whichSatellite == 'OMI':
#            yData = monthlyDict[self.moleculeList[0]]['ime_C'][mask]/6.02214e19
#        elif self.whichSatellite == 'TROPOMI':
#            yData = monthlyDict[self.moleculeList[0]]['ime_C'][mask]        
        weight = monthlyDict[self.moleculeList[0]]['ime_B'][mask]
        A = monthlyDict['L']**2
        L = monthlyDict['L']
        if if_use_ws:
            ime_Q = yData*A*(U/L/ime_f+1/tau)
        else:
            ime_Q = yData*A/tau
        
        Q = np.nansum(ime_Q*weight)/np.nansum(weight)
        return Q
    
    def F_multimonth_OE(self,monthlyDictArray,Q_ap,tau_ap,Sa,
                        universal_f,
                        dateArray=[],
                        ridgeLambda = 3.3e-10,
                        wsRange=(2.,8.),tol=1e-10,maxIteration=100,
                        convergenceThreshold=0):
        
        nmonth = len(monthlyDictArray)
        xx = np.array([])
        yy = np.array([])
        nx_per_month = np.full((nmonth),np.nan)
        for (i,mergedDict) in enumerate(monthlyDictArray):
            if not mergedDict:
                nx_per_month[i] = 0
                continue
            mask = (~np.isnan(mergedDict[self.moleculeList[0]]['ime_ws'])) & (~np.isnan(mergedDict[self.moleculeList[0]]['ime_C'])) \
            & (mergedDict[self.moleculeList[0]]['ime_ws'] >= wsRange[0]) & (mergedDict[self.moleculeList[0]]['ime_ws'] <= wsRange[1])
            xx = np.append(xx,mergedDict[self.moleculeList[0]]['ime_ws'][mask])
            yy = np.append(yy,mergedDict[self.moleculeList[0]]['ime_C'][mask])
            nx_per_month[i] = np.sum(mask)
#        self.nx_per_month = nx_per_month
        inp={};inp['A'] = mergedDict['L']**2;inp['L'] = mergedDict['L'];inp['xx'] = xx;inp['f'] = universal_f;inp['nx_per_month'] = nx_per_month
        y0, dy0dQ, dy0dtau = F_forward12(inp,Q_ap,tau_ap)
        K = np.column_stack((dy0dQ,dy0dtau))
        beta0 = np.concatenate((Q_ap,tau_ap))
        beta = beta0
        Sa_inv = np.linalg.inv(Sa)*ridgeLambda
        Sy_inv = np.diag(np.ones(yy.shape)/ridgeLambda)
        count = 0
        diffNorm = tol+1
        dsigma2 = np.inf
        while(dsigma2 > len(beta)*convergenceThreshold and diffNorm > tol and count < maxIteration):
            try:
                y, dydQ, dydtau = F_forward12(inp,beta[0:nmonth],beta[nmonth:])
                K = np.column_stack((dydQ,dydtau))
                dbeta = np.linalg.inv(Sa_inv+K.T@K)@(K.T@(yy-y)-Sa_inv@(beta-beta0))
                if convergenceThreshold != 0:
                    dsigma2 = dbeta.T@(K.T@Sy_inv@(yy-y)+Sa_inv@(beta-beta0))
                else:
                    norm_dbeta = dbeta/beta0
                    diffNorm = np.linalg.norm(norm_dbeta)
                beta = beta+dbeta
                count = count+1
            except Exception as e:
                self.logger.warning('Fitting error occurred at iteration%d'%count)
                self.logger.warning(e)
                break
            self.logger.info('step %d'%count)
            if convergenceThreshold == 0:
                self.logger.info('relative increment: %.3e'%diffNorm)
            else:
                self.logger.info('dsigma square={:.1f}'.format(dsigma2))
            self.logger.info('Q = %.1f'%np.mean(beta[0:nmonth])+', tau = %.1f'%(np.mean(beta[nmonth:])/3600))
            if count == maxIteration:
                self.logger.warning('max iteration number reached!')
        
        imeFit = IMEOE()
        
        imeFit.Q_post = beta[0:nmonth]
        imeFit.tau_post = beta[nmonth:]
        imeFit.nx_per_month = nx_per_month
        imeFit.xData0 = xx
        imeFit.yData0 = yy
        imeFit.yHat0 = y0
        imeFit.yHat = y
        imeFit.jacobian = K
        imeFit.avk = np.linalg.inv(K.T@K+Sa_inv)@K.T@K
#        imeFit.avk_Sy = np.linalg.inv(K.T@Sy_inv@K+np.linalg.inv(Sa))@K.T@Sy_inv@K
        imeFit.SHat = np.linalg.inv(K.T@Sy_inv@K+np.linalg.inv(Sa))
        SHat = imeFit.SHat
        imeFit.rHat = SHat[0,1]/np.sqrt(SHat[0,0])/np.sqrt(SHat[1,1])
        imeFit.residual0 = yy-y
        imeFit.residualRMS = np.sqrt(np.sum(np.power(yy-y,2))/len(yy))
        imeFit.nIter = count
        imeFit.Jprior = (beta-beta0).T@np.linalg.inv(Sa)@(beta-beta0)
        imeFit.Jobs = (yy-y).T@(yy-y)
        return imeFit
        
        
        
    def F_GaussNewton_OE(self,monthlyDict,ime_f=[],initialGuess=(500.,10800.),
                    ridgeLambda = 1e-10,priorSD=(300,7200),priorRho=0.2,
                    wsRange=(2.,8.),tol=1e-10,maxIteration=100):
        """
        fit emission Q and chemical lifetime tau from ime_C vs. ime_ws using optimal estimation
        monthlyDict:
            one element in monthlyDictArray that output from F_load_monthly_h5, 
            or the mergedDict from F_merge_monthly_data
        ime_f:
            an array of same size as monthlyDict[self.moleculeList[0]]['ime_C']
        intitialGuess:
            prior of (Q,tau)
        ridgeLambda:
            scaling factor of prior error, 0 reduces to no prior. 
            effectively observation error variance. 3 month running climatology gives median rms of 1.05e-5, so 1e-10 is default
        priorSD:
            prior error standard deviation of Q and tau
        priorRho:
            prior error correlation coefficient of Q and tau
        wsRange:
            in m/s, range where ime_C are fitted
        tol:
            tolerance of relative state vector length change
        maxIteration:
            as indicated
        """
        xData = monthlyDict[self.moleculeList[0]]['ime_ws']
        yData = monthlyDict[self.moleculeList[0]]['ime_C']
#        if self.whichSatellite == 'OMI':
#            yData = monthlyDict[self.moleculeList[0]]['ime_C']/6.02214e19
#        elif self.whichSatellite == 'TROPOMI':
#            yData = monthlyDict[self.moleculeList[0]]['ime_C']
        sData = monthlyDict[self.moleculeList[0]]['ime_D']
        if len(ime_f) == 0:
            ime_f = 2*np.ones(xData.shape)
        elif len(ime_f) == 1:
            ime_f = ime_f*np.ones(xData.shape)
        mask = (~np.isnan(xData)) & (~np.isnan(yData)) & (xData >= wsRange[0]) & (xData <= wsRange[1])
        xData0 = xData[mask]
        yData0 = yData[mask]
        sData0 = sData[mask]
        ime_f = ime_f[mask]
        
        inp = {}
        inp['A'] = monthlyDict['L']**2
        inp['L'] = monthlyDict['L']
        inp['ws'] = xData0
        inp['f'] = ime_f
        
        y0,dy0dQ,dy0dtau = F_forward(inp,*initialGuess)
        K = np.column_stack((dy0dQ,dy0dtau))
        beta0 = np.array(initialGuess,dtype=np.float)
        y0 = F_forward(inp,*beta0)[0]
        beta = beta0
        Sa = np.eye(2)
        Sa[0,0] = (priorSD[0]**2)
        Sa[1,1] = (priorSD[1]**2)
        Sa[1,0] = priorRho*priorSD[0]*priorSD[1]
        Sa[0,1] = Sa[1,0]
#        Sa[1,1] = (1/beta0[0]*beta0[1])**2
        Sa_inv = np.linalg.inv(Sa)*ridgeLambda
        count = 0
        diffNorm = tol+1
        self.logger.info('Q = %.1f'%beta[0]+', tau = %.1f'%(beta[1]/3600))
        while (diffNorm > tol and count < maxIteration):
            try:
                y,dydQ,dydtau = F_forward(inp,*beta)
                K = np.column_stack((dydQ,dydtau))
                dbeta = np.linalg.inv(Sa_inv+K.T@K)@(K.T@(yData0-y)-Sa_inv@(beta-beta0))
                norm_dbeta = dbeta/beta0
                diffNorm = np.linalg.norm(norm_dbeta)
                beta = beta+dbeta
                count = count+1
            except Exception as e:
                self.logger.warning('Fitting error occurred at iteration%d'%count)
                self.logger.warning(e)
                break
            self.logger.info('step %d'%count)
            self.logger.info('relative increment: %.3e'%diffNorm)
            self.logger.info('Q = %.1f'%beta[0]+', tau = %.1f'%(beta[1]/3600))
            if count == maxIteration:
                self.logger.warning('max iteration number reached!')
        Sy_inv = np.diag(np.ones(yData0.shape)/ridgeLambda)
        imeFit = IMEOE()
        imeFit.popt = beta
        imeFit.xData0 = xData0
        imeFit.yData0 = yData0
        imeFit.sData0 = sData0
        imeFit.yHat0 = y0
        imeFit.yHat = y
        imeFit.jacobian = K
        imeFit.avk = np.linalg.inv(K.T@K+Sa_inv)@K.T@K
#        imeFit.avk_Sy = np.linalg.inv(K.T@Sy_inv@K+np.linalg.inv(Sa))@K.T@Sy_inv@K
        imeFit.SHat = np.linalg.inv(K.T@Sy_inv@K+np.linalg.inv(Sa))
        SHat = imeFit.SHat
        imeFit.rHat = SHat[0,1]/np.sqrt(SHat[0,0])/np.sqrt(SHat[1,1])
        imeFit.residual0 = yData0-y
        imeFit.residualRMS = np.sqrt(np.sum(np.power(yData0-y,2))/len(yData0))
        imeFit.nIter = count
        imeFit.Jprior = (beta-beta0).T@np.linalg.inv(Sa)@(beta-beta0)
        imeFit.Jobs = (yData0-y).T@(yData0-y)
        return imeFit
        
    def F_fit_ime_C(self,monthlyDict,ime_f=[],initialGuess=(500.,10800.),
                    wsRange=(2.,8.),softResidualThreshold=0.2):
        """
        fit emission Q and chemical lifetime tau from ime_C vs. ime_ws
        monthlyDict:
            one element in monthlyDictArray that output from F_load_monthly_h5, 
            or the mergedDict from F_merge_monthly_data
        ime_f:
            an array of same size as monthlyDict[self.moleculeList[0]]['ime_C']
        intitialGuess:
            prior of (Q,tau)
        wsRange:
            in m/s, range where ime_C are fitted
        softResidualThreshold:
            points with relative (to yHat) residual larger than that will be
            removed, and fit another time
        """
        from scipy.optimize import curve_fit
#        self.logger.info('fitting year %d'%monthlyDict[self.moleculeList[0]]['year_vec']+', month %d'%monthlyDict[self.moleculeList[0]]['month_vec'])
        xData = monthlyDict[self.moleculeList[0]]['ime_ws']
        if 'ime_C_bg' not in monthlyDict[self.moleculeList[0]].keys():
            self.logger.warning('background column does not exist! use zeros')
            yBG = xData*0.
        else:
            yBG = monthlyDict[self.moleculeList[0]]['ime_C_bg']
        yBG = xData*0.
        yData = monthlyDict[self.moleculeList[0]]['ime_C']
#        if self.whichSatellite == 'OMI':
#            yData = monthlyDict[self.moleculeList[0]]['ime_C']/6.02214e19
#            yBG = yBG/6.02214e19
#        elif self.whichSatellite == 'TROPOMI':
#            yData = monthlyDict[self.moleculeList[0]]['ime_C']
        sData = monthlyDict[self.moleculeList[0]]['ime_D']
        if len(ime_f) == 0:
            ime_f = 2*np.ones(xData.shape)
        elif len(ime_f) == 1:
            ime_f = ime_f*np.ones(xData.shape)
        mask = (~np.isnan(xData)) & (~np.isnan(yData)) & (xData >= wsRange[0]) & (xData <= wsRange[1])
        xData0 = xData[mask]
        yData0 = yData[mask]
        sData0 = sData[mask]
        yBG = yBG[mask]
        ime_f = ime_f[mask]
        # first round
        inp = {}
        inp['A'] = monthlyDict['L']**2
        inp['L'] = monthlyDict['L']
        inp['ws'] = xData0
        inp['f'] = ime_f
        inp['Omega_bg'] = yBG
        try:
            popt0,pcov0 = curve_fit(F_delta_omega,inp,yData0,p0=initialGuess)
            yHat0 = F_delta_omega(inp,*popt0)
            residual0 = yData0-yHat0
        except Exception as e:
            self.logger.warning('fitting error occurred');
            print(e)
            imeFit = IME()
            imeFit.xData0 = xData0
            imeFit.yData0 = yData0
            imeFit.sData0 = sData0
            imeFit.yBG = yBG
            imeFit.yHat0 = xData0*np.nan
            imeFit.residual0 = xData0*np.nan
            imeFit.popt0 = np.full((2),np.nan)
            imeFit.pcov0 = np.full((2,2),np.nan)
            imeFit.xData1 = xData0
            imeFit.yData1 = yData0
            imeFit.sData1 = sData0
            imeFit.yHat1 = xData0*np.nan
            imeFit.residual1 = xData0*np.nan
            imeFit.popt1 = np.full((2),np.nan)
            imeFit.pcov1 = np.full((2,2),np.nan)
            return imeFit
            
        imeFit = IME()
        imeFit.xData0 = xData0
        imeFit.yData0 = yData0
        imeFit.sData0 = sData0
        imeFit.yHat0 = yHat0
        imeFit.residual0 = residual0
        imeFit.popt0 = popt0
        imeFit.pcov0 = pcov0
        
        mask = (np.abs(residual0) <= softResidualThreshold*yHat0)
        if np.sum(~mask) > 0:
            self.logger.warning('%d'%np.sum(~mask)+' residuals larger than %d%%'%(softResidualThreshold*100)+', remove and fit again...')
        else:
            imeFit.xData1 = xData0
            imeFit.yData1 = yData0
            imeFit.sData1 = sData0
            imeFit.yBG = yBG
            imeFit.yHat1 = yHat0
            imeFit.residual1 = residual0
            imeFit.popt1 = popt0
            imeFit.pcov1 = pcov0
            return imeFit
        xData1 = xData0[mask];yData1 = yData0[mask];
        sData1 = sData0[mask];yBG = yBG[mask];ime_f = ime_f[mask]
        
        inp['ws'] = xData1
        inp['f'] = ime_f
        inp['Omega_bg'] = yBG
        try:
            popt1,pcov1 = curve_fit(F_delta_omega,inp,yData1,p0=initialGuess)
            yHat1 = F_delta_omega(inp,*popt1)
            residual1 = yData1-yHat1
        except Exception as e:
            self.logger.warning('fitting error occurred');
            print(e)
            yHat1 = np.nan*yData0
            residual1 = np.nan*yData0
            popt1 = np.full((2),np.nan)
            pcov1 = np.full((2,2),np.nan)
        imeFit.xData1 = xData1
        imeFit.yData1 = yData1
        imeFit.sData1 = sData1
        imeFit.yBG = yBG
        imeFit.yHat1 = yHat1
        imeFit.residual1 = residual1
        imeFit.popt1 = popt1
        imeFit.pcov1 = pcov1
        return imeFit
        
    def F_monthly_f_number(self,monthlyDictArray):
        """
        calculate f number using monthlyDictArray and coQArray from previous steps
        """
        return np.array([d['CO']['ime_dx']*d['CO']['ime_sp']*d['CO']['ime_ws']*d['L']\
                  /self.inventories['CO'][ind]/9.8/0.029 for (ind,d) in enumerate(monthlyDictArray)])
    
    def F_merge_monthly_data(self,monthlyDictArray):
        """
        merge monthlyDictArray to a single dict. data fields are weight-
        averaged as needed. The result is mergedDict
        """
        from copy import deepcopy
        if len(monthlyDictArray) == 1:
            self.logger.info('only one month data, no merging is needed')
            mergedDict = monthlyDictArray[0]
            return mergedDict
        mergedDict = {}
        for idict,d0 in enumerate(monthlyDictArray):
            d = deepcopy(d0)
            for k in d[self.moleculeList[0]].keys():
                if 'ime' in k:
                    # clean fields
                    d[self.moleculeList[0]][k][np.isnan(d[self.moleculeList[0]][k])] = 0
            if not d:
                self.logger.warning('empty month')#'%02d'%d[self.moleculeList[0]]['month_vec']+'/%04d'%d[self.moleculeList[0]]['year_vec']+' gives empty data!')
                continue
            if not mergedDict:
                self.logger.info('initiate merge with data in '+'%02d'%d[self.moleculeList[0]]['month_vec']+'/%04d'%d[self.moleculeList[0]]['year_vec'])
                mergedDict = deepcopy(d)
            else:
                self.logger.info('merging with data in '+'%02d'%d[self.moleculeList[0]]['month_vec']+'/%04d'%d[self.moleculeList[0]]['year_vec'])
                for key in self.moleculeList:
                    if key not in mergedDict.keys():
                        self.logger.info(key+' is not a key in the dict')
                        continue
                    ime_B1 = mergedDict[key]['ime_B'].copy()
                    ime_B2 = d[key]['ime_B'].copy()
                    ime_B3 = ime_B1+ime_B2
                    ime_B1[np.isnan(ime_B1)] = 0.
                    ime_B1[np.isnan(ime_B2)] = 0.
                    ime_B1[np.isnan(ime_B3)] = 0.
                    
                    for k in d[key].keys():
                        if k in ['ime_D','ime_B']:
                            # layers of pixels and weights are simply additive
                            mergedDict[key][k][np.isnan(mergedDict[key][k])] = 0
                            d[key][k][np.isnan(d[key][k])] = 0
                            mergedDict[key][k] = mergedDict[key][k]+\
                            d[key][k]
                        elif 'ime' in k:
                            # ime fields (ime_ws, ime_C, etc.) should be weight-averaged
                            mergedDict[key][k][np.isnan(mergedDict[key][k])] = 0
                            # d[key][k][np.isnan(d[key][k])] = 0
                            mergedDict[key][k] = (mergedDict[key][k]*ime_B1+\
                            d[key][k]*ime_B2)/ime_B3
                        elif k == 'A_vec':
                            mergedDict[key][k] = np.column_stack((mergedDict[key][k],d[key][k]))
                        else:
                            # non-ime fields should be concatenated together
                            array1 = mergedDict[key][k].copy()
                            array2 = d[key][k].copy()
                            if array1.ndim == 0:
                                array1 = np.array([array1])
                            if array2.ndim == 0:
                                array2 = np.array([array2])
                            mergedDict[key][k] = np.concatenate((array1,array2))
        return mergedDict    
