#!/usr/bin/env python3
import sys
from pathlib import Path
import errno
import argparse
import subprocess
import time
import shutil
import re
import textwrap
import socket
from datetime import datetime
import glob

from collections import OrderedDict

sys.path.insert(0, str(Path(__file__).resolve().parent / 'python_libs'))
import vtr

def main():
    parse_vtr_flow(sys.argv[1:],prog = sys.argv[0])

def parse_vtr_flow(arg_list, prog=None):
    parse_path = arg_list[0]
    parse_config_file = arg_list[1]

    parse_config_file = vtr.util.verify_file(parse_config_file, "parse config file")

    extra_params = arg_list[2:]
    if parse_config_file is None:
        parse_config_file = vtr.find_vtr_file("vtr_benchmarks.txt")
    
    parse_patterns = vtr.load_parse_patterns(str(parse_config_file)) 

    metrics = OrderedDict()

    extra_params_parsed = OrderedDict()

    for param in extra_params:
        key,value=param.split("=",1)
        extra_params_parsed[key]=value
        print(key,end="\t")
    
    #Set defaults
    for parse_pattern in parse_patterns.values():

        if parse_pattern.default_value() != None:
            metrics[parse_pattern.name()] = parse_pattern.default_value()
        else:
            metrics[parse_pattern.name()] = ""
        print(parse_pattern.name(),end="\t")
    print("")

    for key,value in extra_params_parsed.items():
        print(value,end="\t")

    #Process each pattern
    for parse_pattern in parse_patterns.values():

        #We interpret the parse pattern's filename as a glob pattern
        filepattern = str(Path(parse_path)  / parse_pattern.filename())
        filepaths = glob.glob(filepattern)

        num_files = len(filepaths)

        if num_files > 1:
            raise vtr.InspectError("File pattern '{}' is ambiguous ({} files matched)".format(parse_pattern.filename()), num_files, filepaths)

        elif num_files == 1:
            filepath = filepaths[0]

            assert Path(filepath).exists
            metrics[parse_pattern.name()] = "-1"
            with open(filepath) as f:
                for line in f:
                    if line[0] == "#":
                        line = line[1:]
                    match = parse_pattern.regex().match(line)
                    if match and len(match.groups()):
                        #Extract the first group value
                        metrics[parse_pattern.name()] = match.groups()[0]
            print(metrics[parse_pattern.name()],end="\t")
        else:
            #No matching file, skip
            print("-1",end="\t")
            assert num_files == 0
    print("")
    metrics_filepath = str(Path(parse_path)  / "parse_results.txt")

    #vtr.write_tab_delimitted_csv(metrics_filepath, [metrics])

    return metrics

if __name__ == "__main__":
    retval = main()
    sys.exit(retval)