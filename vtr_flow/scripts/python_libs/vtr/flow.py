import sys
import shutil
import subprocess
import time
import glob
import vtr
from pathlib import Path
from collections import OrderedDict
from vtr import CommandError

VTR_STAGE = vtr.make_enum("odin", "abc", 'ace', "vpr", "lec")
vtr_stages = VTR_STAGE.reverse_mapping.values()

def run(architecture_file, circuit_file, 
                 power_tech_file=None,
                 start_stage=VTR_STAGE.odin, end_stage=VTR_STAGE.vpr, 
                 command_runner=vtr.CommandRunner(), 
                 parse_config_file=None,
                 temp_dir="./temp", 
                 verbosity=0,
                 odin_args=None,
                 abc_args=None,
                 vpr_args=None,
                 keep_intermediate_files=True,
                 keep_result_files=True,
                 min_hard_mult_size=3,
                 check_equivalent=False):
    """
    Runs the VTR CAD flow to map the specificied circuit_file onto the target architecture_file

    Arguments
    ---------
        architecture_file: Architecture file to target
        circuit_file     : Circuit to implement

        power_tech_file  : Technology power file.  Enables power analysis and runs ace

        temp_dir         : Directory to run in (created if non-existant)
        start_stage      : Stage of the flow to start at
        end_stage        : Stage of the flow to finish at
        command_runner   : A CommandRunner object used to run system commands
        parse_config_file: The configuration file defining how to parse metrics from results
        verbosity        : How much output to produce
        vpr_args         : A dictionary of keywork arguments to pass on to VPR
    """
    if vpr_args == None:
        vpr_args = OrderedDict()

    #
    #Initial setup
    #
    vtr.util.verify_file(architecture_file, "Architecture")
    vtr.util.verify_file(circuit_file, "Circuit")
    if(power_tech_file):
        vtr.util.verify_file(power_tech_file, "Power tech")
    architecture_file_basename =architecture_file.name
    circuit_file_basename = circuit_file.name

    circuit_name = circuit_file.stem
    circuit_ext = circuit_file.suffixes
    architecture_name = architecture_file.stem
    architecture_ext = architecture_file.suffixes

    vtr.mkdir_p(temp_dir)
    netlist_ext = ".blif"
    if ".eblif" in circuit_ext:
        netlist_ext = ".eblif"
    #Define useful filenames
    post_odin_netlist = Path(temp_dir)  / (circuit_name + '.odin' + netlist_ext)
    post_abc_netlist =Path(temp_dir)  / (circuit_name + '.abc' + netlist_ext)
    post_ace_netlist =Path(temp_dir)  / (circuit_name + ".ace" + netlist_ext)
    post_ace_activity_file = Path(temp_dir)  / (circuit_name + ".act")
    pre_vpr_netlist = Path(temp_dir)  / (circuit_name + ".pre-vpr" + netlist_ext)
    post_vpr_netlist = Path(temp_dir)  / "vpr.out" #circuit_name + ".vpr.blif"
    lec_base_netlist = None #Reference netlist for LEC
    gen_postsynthesis_netlist = Path(temp_dir) / (circuit_name + "_post_synthesis." + netlist_ext)

    if "blif" in circuit_ext:
        #If the user provided a .blif netlist, we use that as the baseline for LEC
        #(ABC can't LEC behavioural verilog)
        lec_base_netlist = circuit_file_basename

    #Copy the circuit and architecture
    circuit_copy = Path(temp_dir)  / circuit_file.name
    architecture_copy = Path(temp_dir)  / architecture_file.name
    shutil.copy(str(circuit_file), str(circuit_copy))
    shutil.copy(str(architecture_file), str(architecture_copy))


    #There are multiple potential paths for the netlist to reach a tool
    #We initialize it here to the user specified circuit and let downstream 
    #stages update it
    next_stage_netlist = circuit_copy

    #
    # RTL Elaboration & Synthesis
    #
    if should_run_stage(VTR_STAGE.odin, start_stage, end_stage):
        if circuit_ext != ".blif":
            vtr.odin.run(architecture_copy, next_stage_netlist, 
                     output_netlist=post_odin_netlist, 
                     command_runner=command_runner, 
                     temp_dir=temp_dir,
                     odin_args=odin_args,
                     min_hard_mult_size=min_hard_mult_size)

            next_stage_netlist = post_odin_netlist

            if not lec_base_netlist:
                lec_base_netlist = post_odin_netlist

    #
    # Logic Optimization & Technology Mapping
    #
    if should_run_stage(VTR_STAGE.abc, start_stage, end_stage):
        vtr.abc.run(architecture_copy, next_stage_netlist, 
                output_netlist=post_abc_netlist, 
                command_runner=command_runner, 
                temp_dir=temp_dir,
                abc_args=abc_args,
                keep_intermediate_files=keep_intermediate_files)

        next_stage_netlist = post_abc_netlist

        if not lec_base_netlist:
            lec_base_netlist = post_abc_netlist


    #
    # Power Activity Estimation
    #
    if power_tech_file:
        #The user provided a tech file, so do power analysis
        if(not isinstance(power_tech_file,Path)):
            power_tech_file=Path(power_tech_file)

        if should_run_stage(VTR_STAGE.ace, start_stage, end_stage):
            vtr.ace_flow.run(next_stage_netlist, old_netlist = post_odin_netlist, output_netlist=post_ace_netlist, 
                    output_activity_file=post_ace_activity_file, 
                    command_runner=command_runner, 
                    temp_dir=temp_dir)

        if not keep_intermediate_files:
            next_stage_netlist.unlink()
            post_odin_netlist.unlink()

        #Use ACE's output netlistf
        next_stage_netlist = post_ace_netlist

        if not lec_base_netlist:
            lec_base_netlist = post_ace_netlist
        
        #Enable power analysis in VPR
        vpr_args["power"] = True
        #vpr_args["activity_file"] = post_ace_activity_file.name
        vpr_args["tech_properties"] = str(power_tech_file.resolve())

    #
    # Pack/Place/Route
    #
    if should_run_stage(VTR_STAGE.vpr, start_stage, end_stage):
        #Copy the input netlist for input to vpr
        shutil.copyfile(str(next_stage_netlist), str(pre_vpr_netlist))

        if "route_chan_width" in vpr_args:
            #The User specified a fixed channel width
            vtr.vpr.run(architecture_copy, circuit_copy, pre_vpr_netlist, 
                    output_netlist=post_vpr_netlist,
                    command_runner=command_runner, 
                    temp_dir=temp_dir, 
                    vpr_args=vpr_args)
        else:
            #First find minW and then re-route at a relaxed W
            vtr.vpr.run_relax_W(architecture_copy, circuit_copy, pre_vpr_netlist, 
                            output_netlist=post_vpr_netlist,
                            command_runner=command_runner, 
                            temp_dir=temp_dir, 
                            verbosity=verbosity, 
                            vpr_args=vpr_args)

        if not lec_base_netlist:
            lec_base_netlist = pre_vpr_netlist

    #
    # Logical Equivalence Checks (LEC)
    #
    if check_equivalent:
        for file in Path(temp_dir).iterdir():
            if "post_synthesis.blif" in str(file) :
                gen_postsynthesis_netlist = file.name
                break
        vtr.abc.run_lec(lec_base_netlist, gen_postsynthesis_netlist, command_runner=command_runner, temp_dir=temp_dir)
    if(not keep_intermediate_files):
        next_stage_netlist.unlink()
        exts = ('.xml','.sdf','.v')
        if not keep_result_files:
            exts += ('.net', '.place', '.route')
        files = []
        for file in Path(temp_dir).iterdir():
            if file.suffix in exts:
                files.append(file)
        for p in files:
            p.unlink()
        if power_tech_file:
            post_ace_activity_file.unlink()

def parse_vtr_flow(temp_dir, parse_config_file=None, metrics_filepath=None, verbosity=1):
    vtr.mkdir_p(temp_dir)
    if parse_config_file is None:
        parse_config_file = vtr.find_vtr_file("vtr_benchmarks.txt")

    parse_patterns = vtr.load_parse_patterns(parse_config_file) 

    metrics = OrderedDict()

    #Set defaults
    for parse_pattern in parse_patterns.values():

        if parse_pattern.default_value() != None:
            metrics[parse_pattern.name()] = parse_pattern.default_value()
        else:
            metrics[parse_pattern.name()] = ""

    #Process each pattern
    for parse_pattern in parse_patterns.values():

        #We interpret the parse pattern's filename as a glob pattern
        filepattern = str(Path(temp_dir)  / parse_pattern.filename())
        filepaths = glob.glob(filepattern)

        num_files = len(filepaths)

        if num_files > 1:
            raise vtr.InspectError("File pattern '{}' is ambiguous ({} files matched)".format(parse_pattern.filename()), num_files, filepaths)

        elif num_files == 1:
            filepath = filepaths[0]

            assert Path(filepath).exists

            with open(filepath) as f:
                for line in f:
                    match = parse_pattern.regex().match(line)
                    if match:
                        #Extract the first group value
                        metrics[parse_pattern.name()] = match.groups()[0]
        else:
            #No matching file, skip
            assert num_files == 0

    if metrics_filepath is None:
        metrics_filepath = str(Path(temp_dir)  / "parse_results.txt")

    vtr.write_tab_delimitted_csv(metrics_filepath, [metrics])

    return metrics

def should_run_stage(stage, flow_start_stage, flow_end_stage):
    """
    Returns True if stage falls between flow_start_stage and flow_end_stage
    """
    if flow_start_stage <= stage <= flow_end_stage:
        return True
    return False



