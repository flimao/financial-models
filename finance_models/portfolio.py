#!/usr/bin/env python3
#-*- coding: utf-8 -*-

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

class Portfolio:
    """ define Portfolio class. ingest and massage portfolio prices and notionals"""
    def __init__(self, 
        securities_values: pd.DataFrame or pd.Series = None, 
        notionals: pd.DataFrame or pd.Series or None = None,
        na: str or None = 'drop',
        individual: bool = False,
        holding_period: int = 1,
        *args, **kwargs
    ):
        """__init__ function

        Args:
            securities_values (DataFrame or Series): timeseries for prices of each security in a portfolio
                            Each column is a security (if Series, assumed only one security)
            notionals (DataFrame or Series, optional): Quantities of each security. 
                If DataFrame, columns are securities (same as securities_values) and rows are dates (same as securities_values)
                If Series, quantities for each security are on each row and assumed to be constant over time
                If int or float, there is only one security whose notional is fixed in time
                If None, securities_values assumed to be the actual values in the portfolio (as opposed to prices)
            na (bool): drop the NaN values from the portfolio values or not
        """
        # if portfolio is passed directly, transfer their properties to this one
        portfolio = kwargs.get('portfolio', None)

        if portfolio is not None and isinstance(portfolio, Portfolio):
            # set a list of properties to transfer to self
            attr_list = [ 'securities_values', 'notionals', 'portfolio_values', 'portfolio_total' ]
            for attr in attr_list:
                setattr(self, attr, getattr(portfolio, attr))

            return  # nothing else to do

        if securities_values is None:
            # no securities_values provided
            # nothing to be done
            return 

        if isinstance(securities_values, pd.Series):
            # securities_values is Series
            # assumed to be only one security
            # securities_values.name must be set to the security name
            self.securities_values = securities_values.to_frame()
        
        else:
            self.securities_values = securities_values

        if notionals is None:
            # notionals is None, therefore
            # portfolio totals for each security is assumed to be securities_values
            self.notionals = pd.DataFrame(1, columns = self.securities_values.columns, index = self.securities_values.index)
            self.portfolio_values = self.securities_values.copy()
        
        elif isinstance(notionals, pd.Series):
            # notionals is Series, therefore is assumed to be timeseries of notionals
            # for each security
            # multiply each row of securities_values by notional Series
            self.notionals = notionals
            self.portfolio_values = self.securities_values.multiply(self.notionals)
        
        elif isinstance(notionals, pd.DataFrame):
            # notionals is DataFrame
            # multiply elementwise securities_values by notionals
            self.notionals = notionals.reindex(self.securities_values.index).fillna(method = 'ffill')
            self.portfolio_values = self.securities_values.multiply(self.notionals)
        else:
            # notionals is an int or float, therefore all securities assumed to have the same notional in the entire timeseries
            self.notionals = pd.DataFrame(notionals, columns = self.securities_values.columns, index = self.securities_values.index)
            self.portfolio_values = self.securities_values * notionals
        
        # drop NaNs
        if na == 'drop':
            self.portfolio_values.dropna(
                how = 'all',  # only when all values are nans in a given date
                inplace = True,
            )
        elif isinstance(na, str):  # na is string but not drop. filling na
            self.portfolio_values.fillna(
                method = na,
                inplace = True,
            )
        # if na is None, do nothing to address NaNs
        
        # sum each row (time) of portfolio_values
        self.portfolio_total = self.portfolio_values.sum(axis = 1)
        self.portfolio_total.name = 'portfolio_total'

        # holding period
        self.holding_period = holding_period

        # whether we get returns on the consolidated portfolio or for each indvidual asset
        self.individual = individual
    
    def get_returns(self, holding_period = 1, log = False, individual = False):
        if not individual:
            prices = self.portfolio_total
        else:
            prices = self.securities_values

        ret = prices / prices.shift(holding_period)

        if log:
            return np.log(ret)
        else:
            return ret - 1
    
    @property
    def returns(self):
        rets = self.get_returns(holding_period = 1, log = False, individual = self.individual)
        rets.name = 'returns'
        return rets

    @property
    def logreturns(self):
        logrets = self.get_returns(holding_period = 1, log = True, individual = self.individual)
        logrets.name = 'log_returns'
        return logrets


# why is the import statement here, rather than at the top?
# the volatility module imports this module to get a hold of the Portfolio class
# if this import statement were at the top, it would cause a circular import issue.
# we needed to define the Portfolio class before importing the Volatility class
from .volatility import Volatility


class Optimization:
    """ implements optimization from an efficient frontier standpoint """
    
    def __init__(self, 
        nsims: int = 10_000,
        *args, 
        **kwargs
    ):
        kwargs['individual'] = True
        self.volmodel = Volatility(*args, **kwargs)

        self.nsims = nsims

        self.individual_logreturns = self.volmodel.logreturns
        self._cov_matrix = self.individual_logreturns.cov()
        self._means = self.individual_logreturns.mean()

        vol = self.volmodel.vol_pp
        if isinstance(vol, pd.Series):
            self._risks = vol
        
        else:
            self._risks = vol.iloc[-1]

        if self.nsims > 0:
            self._risk_return, self._Ws = self.simulate_weights()

    def simulate_weights(self):
        secs = self.volmodel.securities_values.columns
        n_secs = len(secs)

        pesos = np.random.dirichlet(np.ones(n_secs), size = self.nsims)

        Ws = pd.DataFrame(pesos,
            columns = secs
        )

        muP = Ws @ self._means

        riskP = pd.Series(
            np.sqrt((Ws @ self._cov_matrix @ Ws.transpose()).values.diagonal()),
            index = Ws.index
        )

        risk_return = pd.concat([muP, riskP], axis = 1)
        risk_return.columns = ['return', 'risk']

        return risk_return, Ws
    
    def maximize_returns(self, max_risk):
        idxoptimum = self._risk_return.loc[self._risk_return['risk'] <= max_risk, 'return'].argmax()
        max_ret = self._risk_return.loc[idxoptimum, 'return']
        w = self._Ws.loc[idxoptimum]
        
        return w, max_ret

    def minimize_risk(self, min_return):
        idxoptimum = self._risk_return.loc[self._risk_return['return'] >= min_return, 'risk'].argin()
        min_risk = self._risk_return.loc[idxoptimum, 'risk']
        w = self._Ws.loc[idxoptimum]
        
        return w, min_risk
    
    def plot_risk_return(self, fmt = '.2%'):
        fig, ax = plt.subplots()
        ax.plot(
            self._risk_return['risk'], self._risk_return['return'], 
            'o', color = 'blue', alpha = 0.2, label = 'Simulated portfolios'
        )
        ax.plot(
            self._risks, self._means, 
            'o', color = 'orange', label = 'Original securities'
        )

        for ativo, s, m in zip(
            self.volmodel.securities_values.columns, 
            self._risks,
            self._means, 
        ):
            ax.annotate(ativo, (s, m))

        ax.set_xlabel(r'Risk/volatility (% p.p.)')
        ax.xaxis.set_major_formatter(lambda x, pos: f'{x:{fmt}}')
        ax.set_ylabel(r'Returns (% p.p.)')
        ax.yaxis.set_major_formatter(lambda y, pos: f'{y:{fmt}}')
        ax.set_title(r'Risk vs Return')
        plt.legend()

        return fig
