import os
import sys
import subprocess
import shlex
import platform
import tempfile
import toml
import shutil
import argparse
from .wasm_checker import check_import_section

__version__ = "0.2.10"

src_dir = os.path.dirname(__file__).replace('\\', '/')


#https://stackabuse.com/how-to-print-colored-text-in-python/
#https://stackoverflow.com/questions/287871/how-do-i-print-colored-text-to-the-terminal
HEADER = '\033[95m'
OKBLUE = '\033[94m'
OKCYAN = '\033[96m'
OKGREEN = '\033[92m'
WARNING = '\033[1;33;40m'
FAIL = '\033[91m'
ENDC = '\033[0m'
BOLD = '\033[1m'
UNDERLINE = '\033[4m'

def find_target_dir():
    cur_dir = os.path.abspath(os.curdir)
    target_dir = os.path.join(cur_dir, 'target')
    target_dir = target_dir.replace('\\', '/')
    return target_dir

def print_err(msg):
    print(f'{FAIL}:{msg}{ENDC}')

def print_warning(msg):
    print(f'{WARNING}:{msg}{ENDC}')

def get_rustc_version():
    try:
        result = subprocess.run(["rustc", "--version"], capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print(f"An error occurred while checking the rustc version: {e}")
        return None

def build_contract(package_name, build_mode, target_dir, stack_size):
    os.environ['RUSTFLAGS'] = f'-C link-arg=-zstack-size={stack_size} -Clinker-plugin-lto'
    version = get_rustc_version()
    os.environ['RUSTC_BOOTSTRAP'] = '1'
    print(f"RUSTC_BOOTSTRAP=\"{os.environ['RUSTC_BOOTSTRAP']}\"")
    print(f"RUSTFLAGS=\"{os.environ['RUSTFLAGS']}\"")
    cmd = fr'cargo +stable build --target=wasm32-wasi --target-dir={target_dir} -Zbuild-std --no-default-features {build_mode} -Zbuild-std-features=panic_immediate_abort'
    print(cmd)
    cmd = shlex.split(cmd)
    ret_code = subprocess.call(cmd, stdout=sys.stdout, stderr=sys.stderr)
    if not ret_code == 0:
        sys.exit(ret_code)

    try:
        check_import_section(f'{target_dir}/wasm32-wasi/release/{package_name}.wasm')
    except Exception as e:
        print_err(f'{e}')
        sys.exit(-1)

    if shutil.which('wasm-opt'):
        cmd = f'wasm-opt {target_dir}/wasm32-wasi/release/{package_name}.wasm --signext-lowering -O3 --strip-debug -o {target_dir}/{package_name}.wasm'
        cmd = shlex.split(cmd)
        ret_code = subprocess.call(cmd, stdout=sys.stdout, stderr=sys.stderr)
        if not ret_code == 0:
            sys.exit(ret_code)
    else:
        shutil.copy(f'{target_dir}/wasm32-wasi/release/{package_name}.wasm', f'{target_dir}/{package_name}.wasm')
        print_warning('''
wasm-opt not found! Make sure the binary is in your PATH environment.
We use this tool to optimize the size of your contract's Wasm binary.
It is also used to remove some instructions which are not supported in WASM 1.0
wasm-opt is part of the binaryen package. You can find detailed
installation instructions on https://github.com/WebAssembly/binaryen#tools.
There are ready-to-install packages for many platforms:
* Debian/Ubuntu: apt-get install binaryen
* Homebrew: brew install binaryen
* Arch Linux: pacman -S binaryen
* Windows: binary releases at https://github.com/WebAssembly/binaryen/releases''')

def generate_abi(package_name: str, target_dir: str):
    try:
        temp_dir = tempfile.mkdtemp()
        temp_dir = temp_dir.replace('\\', '/')
        with open(f'{src_dir}/templates/abigen/Cargo.toml', 'r') as f:
            cargo_toml = f.read()
            path_name = os.path.abspath(os.curdir).replace('\\', '/')
            cargo_toml = cargo_toml.format(package_name=package_name, path_name=path_name)
            with open(f'{temp_dir}/Cargo.toml', 'w') as f:
                f.write(cargo_toml)

        with open(f'{src_dir}/templates/abigen/main.rs', 'r') as f:
            main_rs = f.read()
            main_rs = main_rs.format(package_name=package_name, target=f'{target_dir}')
            with open(f'{temp_dir}/main.rs', 'w') as f:
                f.write(main_rs)

        if 'RUSTFLAGS' in os.environ:
            del os.environ['RUSTFLAGS']
        cmd = f'cargo run --package abi-gen --manifest-path={temp_dir}/Cargo.toml --target-dir={target_dir} --release'
        print(cmd)
        cmd = shlex.split(cmd)
        ret_code = subprocess.call(cmd, stdout=sys.stdout, stderr=sys.stderr)
        if not ret_code == 0:
            sys.exit(ret_code)
    finally:
        shutil.rmtree(temp_dir)

def run_builder():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='subparser')

    init = subparsers.add_parser('init')
    init.add_argument('project_name')

    build = subparsers.add_parser('build')
    build.add_argument('--dir-name', default=".")
    build.add_argument(
        '-d', '--debug', action='store_true', help='set to true to enable debug build')
    build.add_argument(
        '-s', '--stack-size', default=8192, help='configure stack size')

    contract = subparsers.add_parser('build-contract')
    contract.add_argument('--dir-name', default=".")
    contract.add_argument(
        '-d', '--debug', action='store_true', help='set to true to enable debug build')
    contract.add_argument(
        '-s', '--stack-size', default=8192, help='configure stack size')

    gen_abi = subparsers.add_parser('generate-abi')
    gen_abi.add_argument('--dir-name', default=".")

    result, unknown = parser.parse_known_args()
    if not result:
        parser.print_usage()
        sys.exit(-1)

    if result.subparser == "init":
        project_name = result.project_name
        with open(f'{src_dir}/templates/init/_Cargo.toml', 'r') as f:
            cargo_toml = f.read().replace('{{name}}', project_name)

        files = {}
        for file_name in ['_Cargo.toml', '.gitignore', 'build.sh', 'lib.rs', 'test.py', 'test.sh', 'pytest.ini']:
            with open(f'{src_dir}/templates/init/{file_name}', 'r') as f:
                if file_name == '_Cargo.toml':
                    file_name = 'Cargo.toml'
                files[file_name] = f.read().replace('{{name}}', project_name)
        try:
            os.mkdir(project_name)
            for file in files:
                file_path = f'{project_name}/{file}'
                with open(file_path, 'w') as f:
                    f.write(files[file])
                if file.endswith('.sh'):
                    if not 'Windows' == platform.system():
                        os.chmod(file_path, 0o755)
        except FileExistsError as e:
            print_err(f'{FAIL}: {e}')
            sys.exit(-1)
    else:
        if not os.path.exists('Cargo.toml'):
            print_err('Cargo.toml not found in current directory!')
            sys.exit(-1)
        with open('Cargo.toml', 'r') as f:
            project = toml.loads(f.read())
            if not 'package' in project:
                print_err('package section not found in Cargo.toml file!')
                sys.exit(-1)
            package_name = project['package']['name']

        if result.dir_name:
            os.chdir(result.dir_name)
        target_dir = find_target_dir()
        if result.subparser == "build":
            if result.debug:
                build_mode = ''
            else:
                build_mode = '--release'
            build_contract(package_name, build_mode, target_dir, result.stack_size)
            generate_abi(package_name, target_dir)
        elif result.subparser == "build-contract":
            if result.debug:
                build_mode = ''
            else:
                build_mode = '--release'
            build_contract(package_name, build_mode, target_dir, result.stack_size)
        elif result.subparser == "generate-abi":
            generate_abi(package_name, target_dir)
        else:
            parser.print_usage()

if __name__ == '__main__':
    run_builder()
