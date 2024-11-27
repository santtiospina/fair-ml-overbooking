import random
import time 
import pickle
import copy
import os
import math
from IPython.display import clear_output

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from scipy import stats
from scipy.stats import t
from sklearn.preprocessing import MinMaxScaler

import pingouin as pg
from pingouin import ttest

import openpyxl as xl
from openpyxl.styles import Font, PatternFill, Border, Side