# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# The ZOffsetPlugin is released under the terms of the AGPLv3 or higher.

from . import MaterialTemperatureOffsetSetting


def getMetaData():
    return {}

def register(app):
    return {"extension": MaterialTemperatureOffsetSetting.MaterialTemperatureOffsetSetting()}
