import os
import subprocess
import sys
import re
import shlex
from dataclasses import dataclass
from copy import deepcopy

# STRUCTURE OF .case FILE:
# EXIT CODE			  	 (1b)  [uint8]		  $ 0
# BYTE LENGTH OF COMMAND (2b)  [uint16]	  	  $ 1
# BYTE LENGTH OF STDOUT  (4b)  [uint32]	  	  $ 2
# BYTE LENGTH OF STDERR  (4b)  [uint32]	  	  $ 3
# BYTE LENGTH OF STDIN   (4b)  [uint32]	  	  $ 4
# COMMAND				($1b)  [String UTF-8] $ 5
# EXPECTED STDOUT		($2b)  [String UTF-8] $ 6
# EXPECTED STDERR		($3b)  [String UTF-8] $ 7
# STDIN           		($4b)  [String UTF-8] $ 8



LOGGING_QUOTE = '`'

@dataclass
class ParsedTestCase:
	expected_exit_code:int = None
	command:str = None
	command_list:list = None
	stdin:str = None
	expected_stdout:str = None
	expected_stderr:str = None

@dataclass
class DumpingParams:
	print_command:bool = True
	print_stdin:bool = True
	print_stdout:bool = True
	print_stderr:bool = True
	print_byte_lengths:bool = False
	


@dataclass
class ConsoleArguments:
	output_file_path:str = None
	silent:bool = False
	unflagged_argv:list = None
	command:str = None
	name:str = None
	stdin:str = None
	dumping_params:DumpingParams = None
	print_files_as_list:bool = False

def error(message:str):
	print(f"[ERROR]",str(message),file=sys.stderr)

def warn(message:str):
    print("[WARN] "+message)

def error_with_exit(message:str):
	error(message)
	sys.exit(1)

custom_assert = lambda condition,message: None if condition else error_with_exit(message)

def cmd_run_echoed(cmd,echo:bool=True, **kwargs):
	if echo: print("[CMD] " + " ".join(cmd))
	return subprocess.run(cmd, **kwargs)

def read_test_case_from_file(input_file_path:str) -> ParsedTestCase:
	result = ParsedTestCase()
	try:
		with open(input_file_path,'rb') as f:
			result.expected_exit_code = int.from_bytes(f.read(1))
			byte_length_of_command	  = int.from_bytes(f.read(2))
			byte_length_of_stdout	  = int.from_bytes(f.read(4))
			byte_length_of_stderr	  = int.from_bytes(f.read(4))
			byte_length_of_stdin	  = int.from_bytes(f.read(4))
			result.command			  = f.read(byte_length_of_command).decode('utf-8')
			result.expected_stdout	  = f.read(byte_length_of_stdout).decode('utf-8')
			result.expected_stderr	  = f.read(byte_length_of_stderr).decode('utf-8')
			result.stdin	  = f.read(byte_length_of_stdin).decode('utf-8')
	except FileNotFoundError:
		error_with_exit(f"File {prepare_string(input_file_path,False)} does not exist")
	result.command_list = shlex.split(result.command)
	return result

UINT16_MAX = 65535
UINT32_MAX = 4294967295

def write_test_case_to_file(output_file_path:str,test_case:ParsedTestCase,arguments:ConsoleArguments=None):
	global UINT16_MAX,UINT32_MAX
	with open(output_file_path,'wb') as f:
		if test_case.expected_exit_code > 255 or test_case.expected_exit_code < 0:
			error_with_exit("Expected exit code should be in range of one byte!")
		f.write((test_case.expected_exit_code).to_bytes())
		byte_command = test_case.command.encode('utf-8')
		byte_stdout = test_case.expected_stdout.encode('utf-8')
		byte_stderr = test_case.expected_stderr.encode('utf-8')
		byte_stdin = test_case.stdin.encode('utf-8')
		custom_assert((byte_len := len(byte_command)) <= UINT16_MAX,f"Byte length of the command ({byte_len}) should be in range of 2 bytes (0-65535)")
		custom_assert((byte_len := len(byte_stdout) ) <= UINT32_MAX,f"Byte length of the stdout  ({byte_len}) should be in range of 4 bytes (0-4294967295)")
		custom_assert((byte_len := len(byte_stderr) ) <= UINT32_MAX,f"Byte length of the stderr  ({byte_len}) should be in range of 4 bytes (0-4294967295)")
		custom_assert((byte_len := len(byte_stdin)  ) <= UINT32_MAX,f"Byte length of the stdin  ({byte_len}) should be in range of 4 bytes (0-4294967295)")
		# If you got these error messages then you are trying to achieve something weird :/
		try:
			f.write((len(byte_command)).to_bytes(2))
			f.write((len(byte_stdout)).to_bytes(4))
			f.write((len(byte_stderr)).to_bytes(4))
			f.write((len(byte_stdin)).to_bytes(4))
		except OverflowError:
			assert False, "Seems like custom assert doesn't work or else this would be unreachable!"
		f.write(byte_command)
		f.write(byte_stdout)
		f.write(byte_stderr)
		f.write(byte_stdin)
		if arguments and not arguments.silent:
			print(f"Succesfully printed testcase to file {prepare_string(output_file_path,False)}!")

def get_test_case_from_command(command:list,console_arguments:ConsoleArguments) -> ParsedTestCase:
	process = cmd_run_echoed(command,not console_arguments.silent, capture_output=True, text=True,input=console_arguments.stdin)
	case = ParsedTestCase()
	case.command = shlex.join(command)
	case.command_list = command
	case.expected_exit_code = process.returncode
	case.expected_stdout = process.stdout
	case.expected_stderr = process.stderr
	case.stdin = console_arguments.stdin
	return case

def unicode_escape(string:str):
	return string.encode('unicode_escape').decode('utf-8')

assert unicode_escape('\n') == '\\n', "Who messed up unicode_escape?"

PREPARE_STRING_CONFIG = {
	'ALLOW_ESCAPING':False,
}

def prepare_string(string,escape=True):
	global PREPARE_STRING_CONFIG
	if not string: return "NULL"
	if not PREPARE_STRING_CONFIG['ALLOW_ESCAPING']:
		return LOGGING_QUOTE+str(string)+LOGGING_QUOTE
	if escape:
		return LOGGING_QUOTE+unicode_escape(str(string))+LOGGING_QUOTE
	else:
		return LOGGING_QUOTE+str(string)+LOGGING_QUOTE

def check_test_case(case:ParsedTestCase,arguments:ConsoleArguments=None) -> bool:
	command = shlex.split(case.command)
	process = cmd_run_echoed(command,not arguments.silent, capture_output=True, text=True,input=case.stdin)

	succesfully:bool = True

	if case.expected_exit_code != process.returncode:
		error(f"Expected exit code {case.expected_exit_code} but got {process.returncode}")
		succesfully = False
	
	if case.expected_stdout != process.stdout:
		error(f"Expected stdout ({len(case.expected_stdout)}):")
		print(prepare_string(case.expected_stdout),file=sys.stderr)
		error(f"Actual stdout ({len(process.stdout)}):")
		print(prepare_string(process.stdout),file=sys.stderr)
		succesfully = False

	if case.expected_stderr != process.stderr:
		error(f"Expected stderr ({len(case.expected_stderr)}):")
		print(prepare_string(case.expected_stderr),file=sys.stderr)
		error(f"Actual stderr ({len(process.stderr)}):")
		print(prepare_string(process.stderr),file=sys.stderr)
		succesfully = False


	return succesfully

STDIN_CAP = 10_000

def parse_flags() -> ConsoleArguments:
	global STDIN_CAP, PREPARE_STRING_CONFIG
	result = ConsoleArguments()
	result.name = sys.argv[0]
	argv_copy = list((deepcopy(sys.argv[1:])))
	result.unflagged_argv = []
	result.stdin = ""
	result.dumping_params = DumpingParams()
	while (len(argv_copy) > 0):
		i = argv_copy.pop(0)
		if (i == '-o'):
			try:
				result.output_file_path = argv_copy.pop(0)
			except IndexError:
				error_with_exit("No output file path was provided.")
		elif (i == '-s'):
			result.silent = True
		elif (i in ('-nostdout','-nostderr','-nostdin','-bytelength','-nostd')):
			def _stdout(): result.dumping_params.print_stdout = False
			def _stderr(): result.dumping_params.print_stderr = False
			def _stdin(): result.dumping_params.print_stdin = False
			def _byte_lengths(): result.dumping_params.print_byte_lengths = True
			actions = {
				'-nostdout'   : [_stdout],
				'-nostderr'   : [_stderr],
				'-nostdin'    : [_stdin],
				'-bytelength' : [_byte_lengths],
				'-nostd' : [_stdout,_stderr,_stdin],
			}
			for j in actions[i]: j()
		elif (i in ('--h','-h','-help','--help','-usage','--usage')):
			usage(result.name,sys.stdout)
			sys.exit(0)
		elif (i == '-readstdin'):
			stdin:str = ""
			_iterator = 0
			print("Provide stdin (to exit print `exit` or `quit`):")
			while _iterator < STDIN_CAP:
				line = None
				try:
					line = input()
				except EOFError:
					break
				if line[:-1] in ('exit','quit','^Q',''):
					break
				else:
					stdin += line
				_iterator += 1
			result.stdin = stdin
		elif (i == '-stdinfile'):
			std_input_file_path = None
			try:
				std_input_file_path = argv_copy.pop(0)
				with open(std_input_file_path,'r') as f:
					result.stdin = f.read()
					print(result.stdin)
			except IndexError:
				error_with_exit("No input file path was provided.")
			except FileNotFoundError:
				error_with_exit(f"File {prepare_string(std_input_file_path,False)} does not exist")
		elif (i == '-commandfile'):
			command_file_path = None
			try:
				command_file_path = argv_copy.pop(0)
				with open(command_file_path,'r') as f:
					result.command = f.read()
			except IndexError:
				error_with_exit("No input file path was provided.")
			except FileNotFoundError:
				error_with_exit(f"File {prepare_string(std_input_file_path,False)} does not exist")
		elif (i == '-notraw'):
			PREPARE_STRING_CONFIG['ALLOW_ESCAPING'] = True
		elif (i == '-aslist'):
			result.print_files_as_list = True
		else:
			result.unflagged_argv.append(i)
	return result

REGEX_CHECKS_CAP = 5_000
AUTO_CHECKS_CAP = 10_000



def replace_every_variable(string:str, _iterator:int) -> str:
	result = string.replace(r'%',str(_iterator)).strip()
	result = result.replace(r'$hex$',str(hex(_iterator)).replace('0x',''))
	result = result.replace(r'$chr$',chr(_iterator)) # I implemented whole math system using regex but it was too much...
	return result

assert (a := replace_every_variable(r'%$hex$$chr$',90)) == '905aZ', f"Who messed up replace_every_variable? Result {a}"

def get_next_test_name(directory:str) -> str: # Kinda heavy function but smart af
	global REGEX_CHECKS_CAP,AUTO_CHECKS_CAP
	list_of_files:list = []
	convention:str = r"test%.case"
	rules:list = []
	for i in os.scandir(directory):
		if i.is_file():
			if i.name == r'.testconvention':
				with open(i.path,'r') as f:
					convention = f.readline()
					rules = [ i.split('//')[0].strip() for i in f.readlines()]
			list_of_files.append(i.name)
	if not convention:
		convention = r"test%.case"
	_iterator = 1
	file_name = None
	if not rules:
		while (True):
			file_name = replace_every_variable(convention,_iterator).strip()
			if file_name not in list_of_files:
				break
			_iterator += 1
			if _iterator > AUTO_CHECKS_CAP:
				error_with_exit("Cannot generate next test name. Or too many test files in one directory")
	else:
		while (True):
			file_name = replace_every_variable(convention,_iterator).strip()
			can_apply_rule = any([re.fullmatch(i,file_name) for i in rules])
			if (file_name not in list_of_files) and (can_apply_rule):
				break
			if _iterator > REGEX_CHECKS_CAP:
				error_with_exit("Cannot generate next test name with any of the regex rules. Or too many test files in one directory")
			_iterator += 1
	return file_name 


def dump_case(case:ParsedTestCase,params:DumpingParams):
	print_if = lambda message,condition: print(message) if condition else None
	print_if(f"Command:\n{case.command}",params.print_command)
	print(f"Expected exit code: {case.expected_exit_code}")
	print_if("Stdin:",params.print_stdin)
	print_if(prepare_string(case.stdin),params.print_stdin)
	print_if("Expected stdout:",params.print_stdout)
	print_if(prepare_string(case.expected_stdout),params.print_stdout)
	print_if("Expected stderr:",params.print_stderr)
	print_if(prepare_string(case.expected_stderr),params.print_stderr)
	print_if(f"Byte length of stdin:   {len(case.stdin.encode('utf-8'))}"  ,params.print_byte_lengths)
	print_if(f"Byte length of stdout:  {len(case.expected_stdout.encode('utf-8'))}" ,params.print_byte_lengths)
	print_if(f"Byte length of stderr:  {len(case.expected_stderr.encode('utf-8'))}" ,params.print_byte_lengths)
	print_if(f"Byte length of command: {len(case.command.encode('utf-8'))}",params.print_byte_lengths)


def check_folder(folder_path:str,console_arguments:ConsoleArguments):
	if not os.path.isdir(folder_path):
		error_with_exit(f"Folder {prepare_string(folder_path,False)} does not exist or it is file")
	files_in_folder = [i for i in os.scandir(folder_path)]
	regex_rules = [r'.*\.case$']
	for i in files_in_folder:
		if i.name == '.testconvention':
			with open(i.path,'r') as f:
				regex_rules = [ i.split('//')[0].strip() for i in f.readlines()[1:]]
			break
	if not regex_rules:
		regex_rules = [r'.*\.case$']
	list_of_failed = []
	for i in files_in_folder:
		if i.name == '.testconvention':
			continue
		can_apply_rule = any([re.fullmatch(j,i.name) for j in regex_rules])
		if can_apply_rule:
			result = check_test_case(read_test_case_from_file(i.path),console_arguments)
			if result and not console_arguments.silent:
				print(f"Test {prepare_string(i.name,False)} passed succesfully!")
			elif not result:
				list_of_failed.append(i.name)
				print(f"Test {prepare_string(i.name,False)} failed!")
	if console_arguments.print_files_as_list:
		print(list_of_failed or "[EMPTY LIST]")


def parse_argv():
	console_arguments : ConsoleArguments = parse_flags()
	argv = console_arguments.unflagged_argv
	try:
		MODE = argv.pop(0)
	except IndexError:
		usage(console_arguments.name,sys.stderr)
		error_with_exit("No mode was provided")
	# match (MODE): Python 3.10 is cool and all, but support of 3.9 is better
	if (MODE == 'check'):
		input_file_path = None
		try:
			input_file_path = argv.pop(0)
		except IndexError:
			error_with_exit("No input directory path was provided")
		result = check_test_case(read_test_case_from_file(input_file_path))
		if result and not console_arguments.silent:
			print(f"Test {prepare_string(input_file_path,False)} passed succesfully!")
	if (MODE == 'checkfolder'):
		input_file_path = None
		try:
			input_file_path = argv.pop(0)
		except IndexError:
			error_with_exit("No input file path was provided")
		check_folder(input_file_path,console_arguments)
	elif (MODE == 'dump'):
		input_file_path = None
		try:
			input_file_path = argv.pop(0)
		except IndexError:
			error_with_exit("No input file path was provided")
		case = read_test_case_from_file(input_file_path)
		dump_case(case,console_arguments.dumping_params)
	elif (MODE == 'write'):
		if not console_arguments.output_file_path:
			console_arguments.output_file_path = get_next_test_name('.')
		if len(argv) < 1 and not console_arguments.command:
			error_with_exit("Not enough cmdlets was provided")
		new_argv = deepcopy(argv)
		if not console_arguments.command:
			case = get_test_case_from_command(new_argv,console_arguments)
		else:
			case = get_test_case_from_command(shlex.split(console_arguments.command),console_arguments)
		write_test_case_to_file(console_arguments.output_file_path,case,console_arguments)
	elif (MODE == 'pywrite'):
		if not console_arguments.output_file_path:
			console_arguments.output_file_path = get_next_test_name('.')
		new_argv = [i for i in deepcopy(argv)]
		if not console_arguments.command:
			case = get_test_case_from_command(shlex.split(console_arguments.command),console_arguments)
			if not console_arguments.silent:
				warn("Pywrite doesn't work with external commands")
		else:
			case = get_test_case_from_command(deepcopy([sys.executable] + new_argv),console_arguments)
		write_test_case_to_file(console_arguments.output_file_path,case,console_arguments)
	elif (MODE == 'update'):
		input_file_path = None
		try:
			input_file_path = argv.pop(0)
		except IndexError:
			error_with_exit("No input file path was provided")
		old_case = read_test_case_from_file(input_file_path)
		command = old_case.command_list
		new_case = get_test_case_from_command(command,console_arguments)
		write_test_case_to_file(input_file_path,new_case,console_arguments)
	elif (MODE == 'help'):
		usage(console_arguments.name,sys.stdout)
		sys.exit(0)
	else:
		usage(console_arguments.name,sys.stderr)
		error_with_exit(f"Unkown mode {MODE}")

def usage(name:str,stream):
	print(f"USAGE: py {name} <MODE> {{MODE PARAMS}} {{FLAGS}}",file=stream)
	print("MODES:",file=stream)
	print("  check <input file path>    -- Checks the single binary *.case file!",file=stream)
	print("  checkfolder <input path>   -- Checks every *.case file in input path!",file=stream)
	print("  dump <input file path>     -- Dumps the test case in human readable way!",file=stream)
	print("  write <cmdlets with args>  -- Creates the *.case file for the cmdlet",file=stream)
	print("  pywrite <*.py file> <args> -- Creates the *.case file for the python file.",file=stream)
	print("  update <input file path>   -- Updates the *.case file with new params",file=stream)
	print("WARNING: pywrite created test cases probably won't work on other machines",file=stream)
	print("  help                        -- Prints this message to stdout and exits with 0 code",file=stream)
	print("FLAGS:",file=stream)
	print("  -o <output file path> -- Changes the output file path to <output file path>",file=stream)
	print("  -s                    -- Makes the program silent.",file=stream)
	print("  -readstdin            -- Read stdin before writing test case.",file=stream)
	print("  -stdinfile            -- Read stdin from file before writing test case.",file=stream)
	print("  -commandfile          -- Read command from file before writing test case.",file=stream)
	print("  -nostdout             -- Don't print stdout in `dump` mode.",file=stream)
	print("  -nostderr             -- Don't print stderr in `dump` mode.",file=stream)
	print("  -nostdin              -- Don't print stderr in `dump` mode.",file=stream)
	print("  -nostd                -- Don't print stdout,stdin,stderr in `dump` mode.",file=stream)
	print("  -bytelength           -- Print byte lengths in `dump` mode.",file=stream)
	print("  -notraw               -- Prepare strings with encoding it using unicode escape",file=stream)
	print("  -aslist               -- Prints failed file names as a list.",file=stream)



def main():
	# write_test_case_to_file("./test3.case",get_test_case_from_command(sys.argv[1:]))
	parse_argv()
	
	


if __name__ == '__main__':
	main()