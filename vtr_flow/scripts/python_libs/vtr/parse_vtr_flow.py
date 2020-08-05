#!/usr/bin/env python3
"""
Module to parse the vtr flow results.
"""
import sys
from pathlib import Path
import glob
import vtr

from collections import OrderedDict



def main():
    """
    main for parse_vtr_flow.py
    """
    parse_vtr_flow(sys.argv[1:])


def parse_vtr_flow(arg_list):
    """
        parse vtr flow output
    """
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
        key, value = param.split("=", 1)
        extra_params_parsed[key] = value
        print(key, end="\t")

    # Set defaults
    for parse_pattern in parse_patterns.values():
        metrics[parse_pattern.name()] = (
            parse_pattern.default_value()
            if parse_pattern.default_value() is not None
            else ""
        )
        print(parse_pattern.name(), end="\t")
    print("")

    for key, value in extra_params_parsed.items():
        print(value, end="\t")

    # Process each pattern
    for parse_pattern in parse_patterns.values():

        # We interpret the parse pattern's filename as a glob pattern
        filepattern = str(Path(parse_path) / parse_pattern.filename())
        filepaths = glob.glob(filepattern)

        num_files = len(filepaths)

        if num_files > 1:
            raise vtr.InspectError(
                "File pattern '{}' is ambiguous ({} files matched)".format(
                    parse_pattern.filename(), num_files
                ),
                num_files,
                filepaths,
            )

        if num_files == 1:
            filepath = filepaths[0]

            assert Path(filepath).exists
            metrics[parse_pattern.name()] = "-1"
            with open(filepath,"r") as file:
                for line in file:
                    if line[0] == "#":
                        line = line[1:]
                    match = parse_pattern.regex().match(line)
                    if match and match.groups():
                        # Extract the first group value
                        metrics[parse_pattern.name()] = match.groups()[0]
            print(metrics[parse_pattern.name()], end="\t")
        else:
            # No matching file, skip
            print("-1", end="\t")
            assert num_files == 0
    print("")
    #metrics_filepath = str(Path(parse_path) / "parse_results.txt")

    # vtr.write_tab_delimitted_csv(metrics_filepath, [metrics])

    return 0


if __name__ == "__main__":
    main()
