# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# The ZOffsetPlugin is released under the terms of the AGPLv3 or higher.

import re
from collections import OrderedDict

from UM.Extension import Extension
from UM.Application import Application
from UM.Settings.SettingDefinition import SettingDefinition
from UM.Settings.DefinitionContainer import DefinitionContainer
from UM.Settings.ContainerRegistry import ContainerRegistry
from UM.Logger import Logger

class TempOffsetPlugin(Extension):
    def __init__(self):
        super().__init__()

        self._application = Application.getInstance()

        self._i18n_catalog = None

        self._settings_dict = OrderedDict()
        self._settings_dict["temp_offset"] = {
            "label": "Temparature Offset",
            "description": "Change printing temperature relative to the material's temperature.",
            "type": "float",
            "unit": "°C",
            "default_value": 0,
            "minimum_value": -100,
            "maximum_value": 100,
            "settable_per_mesh": False,
            "settable_per_extruder": False,
            "settable_per_meshgroup": False
        }
        # self._settings_dict["adhesion_z_offset_extensive_processing"] = {
        #     "label": "Extensive Z Offset Processing",
        #     "description": "Apply the Z Offset throughout the Gcode file instead of affecting the coordinate system. Turning this option on will increase the processing time so it is recommended to leave it off, but it may be needed for some firmware versions.",
        #     "type": "bool",
        #     "default_value": False,
        #     "value": "True if machine_gcode_flavor == \"Griffin\" else False",
        #     "settable_per_mesh": False,
        #     "settable_per_extruder": False,
        #     "settable_per_meshgroup": False
        # }

        ContainerRegistry.getInstance().containerLoadComplete.connect(self._onContainerLoadComplete)

        self._application.getOutputDeviceManager().writeStarted.connect(self._filterGcode)


    def _onContainerLoadComplete(self, container_id):
        if not ContainerRegistry.getInstance().isLoaded(container_id):
            # skip containers that could not be loaded, or subsequent findContainers() will cause an infinite loop
            return

        try:
            container = ContainerRegistry.getInstance().findContainers(id = container_id)[0]
        except IndexError:
            # the container no longer exists
            return

        if not isinstance(container, DefinitionContainer):
            # skip containers that are not definitions
            return
        if container.getMetaDataEntry("type") == "extruder":
            # skip extruder definitions
            return
        
        material_category = container.findDefinitions(key="material")
        temp_offset_setting = container.findDefinitions(key=list(self._settings_dict.keys())[0])
        if material_category and not temp_offset_setting:
            # this machine doesn't have a temp offset setting yet
            material_category = material_category[0]
            for setting_key, setting_dict in self._settings_dict.items():

                definition = SettingDefinition(setting_key, container, material_category, self._i18n_catalog)
                definition.deserialize(setting_dict)

                # add the setting to the already existing platform adhesion settingdefinition
                # private member access is naughty, but the alternative is to serialise, nix and deserialise the whole thing,
                # which breaks stuff
                material_category._children.append(definition)
                container._definition_cache[setting_key] = definition
                container._updateRelations(definition)


    def _filterGcode(self, output_device):
        scene = self._application.getController().getScene()

        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return

        # get setting from Cura
        temp_offset_value = global_container_stack.getProperty("temp_offset", "value")
        if temp_offset_value == 0:
            return

        gcode_dict = getattr(scene, "gcode_dict", {})
        if not gcode_dict: # this also checks for an empty dict
            Logger.log("w", "Scene has no gcode to process")
            return

        dict_changed = False
        hotend_temp_regex = re.compile(r"(M104\s.*S)(\d*\.?\d*)(.*)")

        for plate_id in gcode_dict:
            gcode_list = gcode_dict[plate_id]
            if len(gcode_list) < 2:
                Logger.log("w", "Plate %s does not contain any layers", plate_id)
                continue

            if ";TEMPOFFSETPROCESSED\n" not in gcode_list[0]:
                # look for the first line that contains a G0 or G1 move on the Z axis
                # gcode_list[2] is the first layer, after the preamble and the start gcode

                if ";LAYER:0\n" in gcode_list[1]:
                    # layer 0 somehow got appended to the start gcode chunk
                    chunks = gcode_list[1].split(";LAYER:0\n")
                    gcode_list[1] = chunks[0]
                    gcode_list.insert(2, ";LAYER:0\n" + chunks[1])

                # find the first vertical G0/G1, adjust it and reset the internal coordinate to apply offset to all subsequent moves
                for (list_nr, list) in enumerate(gcode_list):
                    lines = list.split("\n")
                    for (line_nr, line) in enumerate(lines):

                        result = hotend_temp_regex.fullmatch(line)
                        if result:
                            parsed = float(result.group(2))
                            if parsed == 0:
                                Logger.log("d", "Temparature in line %s is 0, skipping", line)
                                continue
                            try:
                                adjusted_temp = round(parsed + temp_offset_value, 5)
                            except ValueError:
                                Logger.log("e", "Unable to process Temparature in line %s", line)
                                continue
                            lines[line_nr] = "M104 " + str(adjusted_temp)+ " ;adjusted by temp offset"
                            break

                    gcode_list[list_nr] = "\n".join(lines)

                gcode_list[0] += ";TEMPOFFSETPROCESSED\n"
                gcode_dict[plate_id] = gcode_list
                dict_changed = True
            else:
                Logger.log("d", "Plate %s has already been processed", plate_id)
                continue

        if dict_changed:
            setattr(scene, "gcode_dict", gcode_dict)
