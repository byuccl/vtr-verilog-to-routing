"""
    module that contains functions to inspect various files to determine important values
"""
import re
from collections import OrderedDict
from pathlib import Path
try:
    # Try for the fast c-based version first
    import xml.etree.cElementTree as ET
except ImportError:
    # Fall back on python implementation
    import xml.etree.ElementTree as ET

from vtr.error import InspectError
from vtr import load_config_lines

class ParsePattern:
    def __init__(self, name, filename, regex_str, default_value=None):
        self._name = name
        self._filename = filename
        self._regex = re.compile(regex_str)
        self._default_value = default_value

    def name(self):
        return self._name

    def filename(self):
        return self._filename

    def regex(self):
        return self._regex

    def default_value(self):
        return self._default_value

class PassRequirement(object):
    def __init__(self, metric):
        self._metric = metric
        self._type = type

    def metric(self):
        return self._metric

    def type(self):
        raise NotImplementedError()

    def check_passed(golden_value, check_value):
        raise NotImplementedError()

class EqualPassRequirement(PassRequirement):
    def __init__(self, metric):
        super(EqualPassRequirement, self).__init__(metric)

    def type(self):
        return "Equal"

    def check_passed(self, golden_value, check_value, check_string = "golden value"):
        if golden_value == check_value:
            return True, ""
        else:
            return False, "Task value '{}' does not match {} '{}'".format(check_value, check_string, golden_value)

class RangePassRequirement(PassRequirement):

    def __init__(self, metric, min_value=None, max_value=None):
        super(RangePassRequirement, self).__init__(metric)

        if max_value < min_value:
            raise InspectError("Invalid range specification (max value larger than min value)")

        self._min_value = min_value
        self._max_value = max_value

    def type(self):
        return "Range"

    def min_value(self):
        return self._min_value

    def max_value(self):
        return self._max_value

    def check_passed(self, golden_value, check_value, check_string = "golden value"):
        if golden_value == None and check_value == None:
            return True, "both golden and check are None"
        elif golden_value == None and check_value != None:
            return False, "{} is None, but check value is {}".format(check_string,check_value)
        elif golden_value != None and check_value == None:
            return False, "{} is {}, but check value is None".format(check_string,golden_value)

        assert golden_value != None
        assert check_value != None

        original_golden_value = golden_value
        try:
            golden_value = float(golden_value)
        except ValueError as e:
            raise InspectError("Failed to convert {} '{}' to float".format(check_string, golden_value))
        original_check_value = check_value
        try:
            check_value = float(check_value)
        except ValueError as e:
            raise InspectError("Failed to convert check value '{}' to float".format(check_value))

        norm_check_value = None
        if golden_value == 0.: #Avoid division by zero

            if golden_value == check_value:
                return True, "golden and check both equal 0"
            else:
                norm_check_value = float("inf")
        else:
            norm_check_value = check_value / golden_value

        if original_check_value == original_golden_value:
            return True, "Check value equal to {}".format(check_string)
        
        else:

            if self.min_value() <= norm_check_value <= self.max_value():
                return True, "relative value within range"
            else:
                return False, "relative value {} outside of range [{},{}]".format(norm_check_value, self.min_value(), self.max_value())

class RangeAbsPassRequirement(PassRequirement):

    def __init__(self, metric, min_value=None, max_value=None,abs_threshold=None):
        super().__init__(metric)

        if max_value < min_value:
            raise InspectError("Invalid range specification (max value larger than min value)")

        self._min_value = min_value
        self._max_value = max_value
        self._abs_threshold = abs_threshold

    def type(self):
        return "Range"

    def min_value(self):
        return self._min_value

    def max_value(self):
        return self._max_value
    def abs_threshold(self):
        return self._abs_threshold

    def check_passed(self, golden_value, check_value, check_string = "golden value"):
        if golden_value == None and check_value == None:
            return True, "both {} and check are None".format(check_string)
        elif golden_value == None and check_value != None:
            return False, "{} is None, but check value is {}".format(check_string, check_value)
        elif golden_value != None and check_value == None:
            return False, "{} is {}, but check value is None".format(check_string, golden_value)

        assert golden_value != None
        assert check_value != None
        original_golden_value = golden_value
        try:
            golden_value = float(golden_value)
        except ValueError as e:
            raise InspectError("Failed to convert {} '{}' to float".format(check_string,golden_value))
        original_check_value = check_value
        try:
            check_value = float(check_value)
        except ValueError as e:
            raise InspectError("Failed to convert check value '{}' to float".format(check_value))
        norm_check_value = None
        if golden_value == 0.: #Avoid division by zero

            if golden_value == check_value:
                return True, "{} and check both equal 0".format(check_string)
            else:
                norm_check_value = float("inf")
        
        else:
            norm_check_value = check_value / golden_value

        if original_check_value == original_golden_value:
            return True, "Check value equal to {}".format(check_string)

        if (self.min_value() <= norm_check_value <= self.max_value()) or abs(check_value - golden_value) < self.abs_threshold():
            return True, "relative value within range"
        else:
            return False, "relative value {} outside of range [{},{}] and above absolute threshold {}".format(norm_check_value, self.min_value(), self.max_value(),self.abs_threshold())
 
class ParseResults:
    def __init__(self):
        self._metrics = OrderedDict()

    def primary_keys(self):
        return ("architecture", "circuit","script_params")

    def add_result(self, arch, circuit, parse_result, script_param = None):
        script_param = load_script_param(script_param)
        self._metrics[(arch, circuit, script_param)] = parse_result

    def metrics(self, arch, circuit, script_param = None):
        script_param = load_script_param(script_param)
        if (arch, circuit, script_param) in self._metrics:
            return self._metrics[(arch, circuit, script_param)]
        else:
            return None

    def all_metrics(self):
        return self._metrics

def load_script_param(script_param):
    if script_param and "common" not in script_param:
        script_param = "common_" + script_param
    if script_param:
        script_param = script_param.replace(" ","_")
    else:
        script_param = "common"
    return script_param

def load_parse_patterns(parse_config_filepath):
    parse_patterns = OrderedDict()

    for line in load_config_lines(parse_config_filepath):

        components = line.split(';')

    
        if len(components) == 3 or len(components) == 4:

            name = components[0]
            filepath = components[1]
            regex_str = components[2]

            default_value = None
            if len(components) == 4:
                default_value = components[3]

            if name not in parse_patterns:
                parse_patterns[name] = ParsePattern(name, filepath, regex_str, default_value)
            else:
                raise InspectError("Duplicate parse pattern name '{}'".format(name), parse_config_filepath)

        else:
            raise InspectError("Invalid parse format line: '{}'".format(line), parse_config_filepath)

    return parse_patterns

def load_pass_requirements(pass_requirements_filepath):
    parse_patterns = OrderedDict()

    for line in load_config_lines(pass_requirements_filepath):

        components = line.split(';')
    
        if len(components) == 2:

            metric = components[0]
            expr = components[1]

            if metric not in parse_patterns:
                func, params_str = expr.split("(")
                params_str = params_str.rstrip(")")
                if params_str == "":
                    params = []
                else:
                    params = params_str.split(",")

                if func == "Range":
                    if len(params) != 2:
                        raise InspectError("Range() pass requirement function requires two arguments", pass_requirements_filepath)

                    parse_patterns[metric] = RangePassRequirement(metric, float(params[0]), float(params[1]))
                elif func == "RangeAbs":
                    if len(params) != 3:
                        raise InspectError("RangeAbs() pass requirement function requires two arguments", pass_requirements_filepath)

                    parse_patterns[metric] = RangeAbsPassRequirement(metric, float(params[0]), float(params[1]), float(params[2]))
                elif func == "Equal":
                    if len(params) != 0:
                        raise InspectError("Equal() pass requirement function requires no arguments", pass_requirements_filepath)
                    parse_patterns[metric] = EqualPassRequirement(metric)
                else:
                    raise InspectError("Unexpected pass requirement function '{}' for metric '{}'".format(func, metric), pass_requirements_filepath)

            else:
                raise InspectError("Duplicate pass requirement for '{}'".format(metric), pass_requirements_filepath)

        else:
            raise InspectError("Invalid pass requirement format line: '{}'".format(line), pass_requirements_filepath)

    return parse_patterns

def load_parse_results(parse_results_filepath, primary_key_set=None):
    header = []

    parse_results = ParseResults()
    if not Path(parse_results_filepath).exists():
        return parse_results

    with open(parse_results_filepath) as file:
        for lineno, row in enumerate(file):
            if row[0] == "+":
                row = row[1:]
            elements = [elem.strip() for elem in row.split("\t")]

            if lineno == 0:
                header = elements
            else:
                primary_keys = OrderedDict()
                result = OrderedDict()

                arch=None
                circuit=None
                script_param=None
                for i, elem in enumerate(elements):
                    metric = header[i]

                    if elem == "":
                        elem = None

                    if metric == "arch":
                        metric = "architecture"

                    if metric == "architecture":
                        arch = elem
                    elif metric == "circuit":
                        circuit = elem
                    elif metric == "script_params":
                        script_param = elem

                    result[metric] = elem

                if not (arch and circuit):
                    print(parse_results_filepath)
                
                parse_results.add_result(arch, circuit, result, script_param)

    return parse_results

def determine_lut_size(architecture_file):
    """
    Determines the maximum LUT size (K) in an architecture file.

    Assumes LUTs are represented as BLIF '.names'
    """
    arch_xml = ET.parse(architecture_file).getroot()

    lut_size = 0
    saw_blif_names = False
    for elem in arch_xml.findall(".//pb_type"):  # Xpath recrusive search for 'pb_type'
        blif_model = elem.get("blif_model")
        if blif_model and blif_model == ".names":
            saw_blif_names = True
            input_port = elem.find("input")

            input_width = int(input_port.get("num_pins"))
            assert input_width > 0

            # Keep the maximum lut size found (i.e. fracturable architectures)
            lut_size = max(lut_size, input_width)

    if saw_blif_names and lut_size == 0:
        raise InspectError(
            "Could not identify valid LUT size (K)", filename=architecture_file
        )

    return lut_size


def determine_memory_addr_width(architecture_file):
    """
    Determines the maximum RAM block address width in an architecture file

    Assumes RAMS are represented using the standard VTR primitives
    (.subckt single_port_ram, .subckt dual_port_ram etc.)
    """
    arch_xml = ET.parse(architecture_file).getroot()

    mem_addr_width = 0
    saw_ram = False
    for elem in arch_xml.findall(".//pb_type"):  # XPATH for recursive search
        blif_model = elem.get("blif_model")
        if blif_model and "port_ram" in blif_model:
            saw_ram = True
            for input_port in elem.findall("input"):
                port_name = input_port.get("name")
                if "addr" in port_name:
                    input_width = int(input_port.get("num_pins"))
                    mem_addr_width = max(mem_addr_width, input_width)

    if saw_ram and mem_addr_width == 0:
        raise InspectError(
            "Could not identify RAM block address width", filename=architecture_file
        )

    return mem_addr_width


def determine_min_w(log_filename):
    """
        determines the miniumum width.
    """
    min_w_regex = re.compile(
        r"\s*Best routing used a channel width factor of (?P<min_w>\d+)."
    )
    with open(log_filename) as file:
        for line in file:
            match = min_w_regex.match(line)
            if match:
                return int(match.group("min_w"))

    raise InspectError(
        "Failed to find minimum channel width.", filename=log_filename
    )
