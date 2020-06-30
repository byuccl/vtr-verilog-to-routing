import shutil
from pathlib import Path
from vtr import  mkdir_p, find_vtr_file, determine_lut_size, verify_file
from vtr.error import VtrError, InspectError, CommandError

def run(architecture_file, circuit_file,
        output_netlist, command_runner,
        temp_dir=".", log_filename="abc.out",
        abc_exec=None, abc_script=None, abc_rc=None,
        use_old_abc_script = False, abc_args = None, keep_intermediate_files=1):

    mkdir_p(temp_dir)

    verify_file(architecture_file, "Architecture")
    verify_file(circuit_file, "Circuit")
    verify_file(output_netlist, "Output netlist", False)
        
    blackbox_latches_script = find_vtr_file("blackbox_latches.pl")
    clk_list = []
    clk_log_file = "report_clk_out.out"
    #
    # Parse arguments
    #
    abc_flow_type = 2
    abc_run_args = ""
    use_old_latches_restoration_script = 0
    lut_size = None
    for  key, value in abc_args.items():
        if(key=="iterative_bb"):
            abc_flow_type=2
        elif(key=="blanket_bb"):
            abc_flow_type=3
        elif(key=="once_bb"):
            abc_flow_type=1
        elif(key=="use_old_latches_restoration_script"):
            use_old_latches_restoration_script = 1
        elif(key=="lut_size"):
            lut_size=value
        else:
            if value == True:
                abc_run_args += ["--" + arg]
            elif value == False:
                pass
            else:
                abc_run_args += ["--" + arg, str(value)]
            
    if(lut_size == None):
        lut_size = determine_lut_size(str(architecture_file))

    if(abc_flow_type):
        populate_clock_list(circuit_file,blackbox_latches_script,clk_list,command_runner,temp_dir,log_filename)

    if abc_exec == None:
        abc_exec = find_vtr_file('abc', is_executable=True)
    
    if abc_rc == None:
        abc_rc = Path(abc_exec).parent / 'abc.rc'

    shutil.copyfile(str(abc_rc), str(Path(temp_dir) / 'abc.rc'))

    

    iterations=len(clk_list)
    
    if(iterations==0 or abc_flow_type != 2):
        iterations=1

    for i in range(0, iterations):
        pre_abc_blif= Path(temp_dir) / (str(i)+"_" + circuit_file.name)
        post_abc_blif = Path(temp_dir) / (str(i)+"_"+output_netlist.name)
        post_abc_raw_blif = Path(temp_dir) / (str(i)+"_"+output_netlist.with_suffix('').stem+".raw.abc.blif")
        if(abc_flow_type==3):
            cmd = [blackbox_latches_script, "--input", circuit_file.name,"--output",pre_abc_blif.name]
            command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename=str(i)+"_blackboxing_latch.out", indent_depth=1)
        
        elif(len(clk_list)>i):
            cmd = [blackbox_latches_script,"--clk_list", clk_list[i], "--input", circuit_file.name,"--output",pre_abc_blif.name]
            command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename=str(i)+"_blackboxing_latch.out", indent_depth=1)
        else:
            pre_abc_blif = circuit_file
        
        if abc_script == None:
           
            abc_script = ['echo ""',
                        'echo "Load Netlist"',
                        'echo "============"',
                        'read {pre_abc_blif}'.format(pre_abc_blif=pre_abc_blif.name),
                        'time',
                        'echo ""',
                        'echo "Circuit Info"',
                        'echo "=========="',
                        'print_stats',
                        'print_latch',
                        'time',
                        'echo ""',
                        'echo "LUT Costs"',
                        'echo "========="',
                        'print_lut',
                        'time',
                        'echo ""',
                        'echo "Logic Opt + Techmap"',
                        'echo "==================="',
                        'strash',
                        'ifraig -v',
                        'scorr -v',
                        'dc2 -v',
                        'dch -f',
                        'if -K {lut_size} -v'.format(lut_size=lut_size),
                        'mfs2 -v',
                        'print_stats',
                        'time',
                        'echo ""',
                        'echo "Output Netlist"',
                        'echo "=============="',
                        'write_hie {pre_abc_blif} {post_abc_raw_blif}'.format(pre_abc_blif=pre_abc_blif.name, post_abc_raw_blif=post_abc_raw_blif.name),
                        'time;']

            if(use_old_abc_script):
                abc_script = ['read {pre_abc_blif}'.format(pre_abc_blif=pre_abc_blif.name),
                        'time',
                        'resyn', 
                        'resyn2', 
                        'if -K {lut_size}'.format(lut_size=lut_size),
                        'time',
                        'scleanup',
                        'write_hie {pre_abc_blif} {post_abc_raw_blif}'.format(pre_abc_blif=pre_abc_blif.name, post_abc_raw_blif=post_abc_raw_blif.name),
                        'print_stats']

            abc_script = "; ".join(abc_script)

        cmd = [abc_exec, '-c', abc_script]
        
        if(abc_run_args):
            cmd.append(abc_run_args)
        log_file = Path(log_filename)
        command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename=log_file.stem+str(i)+log_file.suffix, indent_depth=1)
        
        if(abc_flow_type != 3 and len(clk_list)>i):
            cmd = [blackbox_latches_script,"--restore", clk_list[i], "--input", post_abc_raw_blif.name,"--output",post_abc_blif.name]
            command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename="restore_latch" + str(i) + ".out", indent_depth=1)
        else:
            if(use_old_latches_restoration_script):
                restore_multiclock_info_script = find_vtr_file("restore_multiclock_latch_information.pl")
            else:
                restore_multiclock_info_script = find_vtr_file("restore_multiclock_latch.pl")

            cmd = [restore_multiclock_info_script, pre_abc_blif.name, post_abc_raw_blif.name ,post_abc_blif.name]
            command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename="restore_latch" + str(i) + ".out", indent_depth=1)
        if(abc_flow_type != 2):
            break
    
    cmd = [blackbox_latches_script, "--input", post_abc_blif.name,"--output",output_netlist.name,"--vanilla"]
    command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename="restore_latch" + str(i) + ".out", indent_depth=1)
    if(not keep_intermediate_files):
        files = []
        for file in Path(temp_dir).iterdir():
            if file.suffix in ('.dot','.v','.rc'):
                files.append(file)
        for p in files:
            p.unlink()


def populate_clock_list(circuit_file,blackbox_latches_script,clk_list,command_runner,temp_dir,log_filename):
    clk_list_path = Path(temp_dir) / "report_clk.out"
    cmd = [blackbox_latches_script, "--input", circuit_file.name,"--output_list", clk_list_path.name]
    command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename=log_filename, indent_depth=1)
    with clk_list_path.open('r') as f:
         clk_list.append(f.readline().strip('\n'))

def run_lec(reference_netlist, implementation_netlist, command_runner, temp_dir=".", log_filename="abc.dec.out", abc_exec=None):
    """
    Run Logical Equivalence Checking (LEC) between two netlists using ABC
    """
    mkdir_p(temp_dir)

    if abc_exec == None:
        abc_exec = find_vtr_file('abc', is_executable=True)

        abc_script = 'dsec {ref} {imp}'.format(ref=reference_netlist, imp=implementation_netlist),
        abc_script = "; ".join(abc_script)

    cmd = [abc_exec, '-c', abc_script]

    output, returncode = command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename=log_filename, indent_depth=1)

    #Check if ABC's LEC engine passed
    lec_passed, errored = check_abc_lec_status(output)
    if errored:
        abc_script = 'cec {ref} {imp}'.format(ref=reference_netlist, imp=implementation_netlist),
        abc_script = "; ".join(abc_script)
        cmd = [abc_exec, '-c', abc_script]
        output, returncode = command_runner.run_system_command(cmd, temp_dir=temp_dir, log_filename="abc.cec.out", indent_depth=1)    
        lec_passed, errored = check_abc_lec_status(output)
    if lec_passed is None:
        raise InspectError("Could not determine Logical Equivalence Check status between {input} <-> {output}".format(input=reference_netlist, output=implementation_netlist), filename=log_filename)
    elif lec_passed is False:
        raise InspectError("Logical Equivalence Check failed between {input} <-> {output}".format(input=reference_netlist, output=implementation_netlist), filename=log_filename)
    
    assert lec_passed

def check_abc_lec_status(output):
    equivalent = None
    errored = False
    for line in output:
        if "Error: The network has no latches." in line:
            errored = True
        if line.startswith("Networks are NOT EQUIVALENT"):
            equivalent = False
        elif line.startswith("Networks are equivalent"):
            equivalent = True

    #Returns None if could not determine LEC status
    return equivalent, errored
