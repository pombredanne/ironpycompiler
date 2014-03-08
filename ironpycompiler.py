#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Helps to compile IronPython scripts, using pyc.py.

This module helps you compile your IronPython scripts requiring the 
Python standard library (or third-party pure-Python modules) into a 
.NET assembly, using pyc.py.

Please note that this module should be used on not IronPython but 
CPython, because :mod:`modulefinder` of IronPython does not work 
correctly.
"""

__author__ = "Hamukichi (Nombiri)"
__version__ = "0.5.0"
__date__ = "2014-03-08"
__licence__ = "MIT License"

import sys
import itertools
import os
import glob
import modulefinder
import tempfile
import subprocess
import argparse

# Third-party modules
import six

IPYREGKEYS = ["SOFTWARE\\IronPython", 
"SOFTWARE\\Wow6432Node\\IronPython"]
IPYEXE = "ipy.exe"

class PCHError(Exception):
    """This is the base class for exceptions in this module.
    """
    pass

class IronPythonDetectionError(PCHError):
    """This exception will be raised when IronPython cannot be found in 
    your system.
    
    :param str executable: The name of the IronPython executable looked 
    for.
    """
    
    def __init__(self, exectuable):
        self.executable = str(executable)
    
    def __str__(self):
        return "IronPython (%s) cannot be found." % self.executable

def detect_ipy(regkeys = IPYREGKEYS, executable = IPYEXE):
    """This function returns the list of the paths to the IronPython 
    directories.
    
    This function searches in the Windows registry and PATH for 
    IronPython. If IronPython cannot be found in your system, 
    :exc:`IronPythonDetectionError` will occur.
    
    :param list regkeys: (optional) The IronPython registry keys that 
    should be looked for.
    :param str executable: (optional) The name of the IronPython 
    executable.
    :rtype: list
    """
    
    ipydirpaths = set()
    
    # 可能ならば、IronPythonキーをレジストリから読み込む
    ipybasekey = None
    try:
        for key in regkeys:
            try:
                ipybasekey = six.moves.winreg.OpenKey(
                six.moves.winreg.HKEY_LOCAL_MACHINE, key)
                break # キーが見つかれば終わる
            except WindowsError as e: # キーが存在しないときなど
                continue
    except ImportError as e:
        pass
    
    # レジストリからIronPythonへのパスを取得する
    if ipybasekey:
        itr = itertools.count()
        # インストールされているIronPythonのバージョンを取得する
        ipyvers = []
        for idx in itr:
            try:
                ipyvers.append(
                six.moves.winreg.EnumKey(ipybasekey, idx))
            except WindowsError as e: # 対応するサブキーがなくなったら
                break
        # IronPythonへのパスを取得する
        for ver in ipyvers:
            with six.moves.winreg.OpenKey(ipybasekey, 
            ver + "\\InstallPath") as ipypathkey:
                ipydirpaths.add(os.path.dirname(
                six.moves.winreg.QueryValue(ipypathkey, None)))
        # IronPythonキーを閉じる
        ipybasekey.Close()
    
    # 環境変数PATHからIronPythonへのパスを取得する
    for path in os.environ["PATH"].split(os.pathsep):
        for match_path in glob.glob(os.path.join(path, executable)):
            if os.access(match_path, os.X_OK):
                ipydirpaths.add(os.path.dirname(match_path))
    
    if len(ipydirpaths) == 0:
        raise IronPythonDetectionError(executable)
    
    return sorted(list(ipydirpaths), reverse = True)

class ModuleCompiler:
    """This class finds the modules required by your script and 
    create a .NET assembly.
    
    By default this class searches for pure-Python modules in the 
    IronPython standard library and the CPython site-packages directory.
    
    :param list paths_to_scripts: Specify the paths to your scripts. 
    In creating a .EXE file, the first element of this list must be the 
    path to the main file of your project.
    :param str ipy_dir: Specify the IronPython directory, or it will be
    automatically detected using :func:`detect_ipy()`.
    """
    
    def __init__(self, paths_to_scripts, ipy_dir = None):
        """ Initialization.
        """
        
        if ipy_dir is None:
            self.ipy_dir = detect_ipy()[0]
        else:
            self.ipy_dir = ipy_dir
        
        self.paths_to_scripts = [os.path.abspath(x) for x in 
        paths_to_scripts] # コンパイルすべきスクリプトたち
        
        self.dirs_of_modules = None # 依存モジュールたちのディレクトリ
        self.compilable_modules = set() # ファイルパスの集合
        self.uncompilable_modules = set() # モジュール名の集合、非必須
        self.response_file = None # pyc.pyに渡すレスポンスファイル
        self.pyc_stdout = None # pyc.pyから得た標準出力
        self.pyc_stderr = None # pyc.pyから得た標準エラー出力
    
    def check_compilability(self, dirs_of_modules = None):
        """Check the compilability of the modules required by the 
        scripts you specified.
        
        :param list dirs_of_modules: Specify the paths of the 
        directories where the modules your scripts require exist, or 
        this method searches for pure-Python modules in the IronPython 
        standard library and the CPython site-packages directory.
        """
        
        self.dirs_of_modules = dirs_of_modules
        if self.dirs_of_modules is None:
                self.dirs_of_modules = [os.path.join(self.ipy_dir, 
                "Lib")]
                self.dirs_of_modules += [p for p in sys.path if 
                "site-packages" in p]
        
        # 各スクリプトが依存するモジュールを探索する
        for script in self.paths_to_scripts:
            mf = modulefinder.ModuleFinder(path = self.dirs_of_modules)
            mf.run_script(script)
            self.uncompilable_modules |= set(mf.badmodules.keys())
            for name, module in mf.modules.iteritems():
                path_to_module = module.__file__
                if path_to_module is None:
                    continue
                elif os.path.splitext(path_to_module)[1] == ".pyd":
                    self.uncompilable_modules.add(name)
                    continue
                else:
                    self.compilable_modules.add(
                    os.path.abspath(path_to_module))
        self.compilable_modules -= set(self.paths_to_scripts)
    
    def call_pyc(self, args, delete_resp = True, executable = IPYEXE):
        """Call pyc.py in order to compile your scripts.
        
        In general use this method is not supposed to be called 
        directly. It is recommended that you use 
        :meth:`create_executable` or :meth:`create_dll` instead.
        
        :param list args: Specify the arguments that should be sent to 
        pyc.py.
        :param bool delete_resp: (optional) Specify whether to delete the 
        response file after compilation or not. 
        :param str executable: (optional) Specify the name of the 
        Ironpython exectuable.
        """
        
        # レスポンスファイルを作る
        self.response_file = tempfile.mkstemp(suffix = ".txt", 
        text = True)
        
        # レスポンスファイルに書き込む
        for line in args:
            os.write(self.response_file[0], line + "\n")
        
        # レスポンスファイルを閉じる
        os.close(self.response_file[0])
        
        # pyc.pyを実行する
        ipy_args = [os.path.splitext(executable)[0], 
        os.path.join(self.ipy_dir, "Tools", "Scripts", "pyc.py"),
        "@" + self.response_file[1]]
        ipy_exe = os.path.abspath(os.path.join(self.ipy_dir, 
        executable))
        sp = subprocess.Popen(args = ipy_args, executable = ipy_exe, 
        stdin = subprocess.PIPE, stdout = subprocess.PIPE, 
        stderr = subprocess.STDOUT)
        (self.pyc_stdout, self.pyc_stderr) = sp.communicate()
        sp.terminate()
        
        # レスポンスファイルを削除する
        if delete_resp:
            os.remove(self.response_file[1])
        
    def create_dll(self, out = None, delete_resp = True, executable = IPYEXE):
        """Compile your scripts into a DLL file (.NET library 
        assembly) using pyc.py.
        
        :param str out: (optional) Specify the name of the DLL file 
        that should be created.
        :param bool delete_resp: (optional) Specify whether to delete the 
        response file after compilation or not. 
        :param str executable: (optional) Specify the name of the 
        Ironpython exectuable.
        """
        
        if self.compilable_modules == set():
            self.check_compilability()
        
        # pycに送る引数
        pyc_args = ["/target:dll"]
        if out is not None:
            pyc_args.append("/out:" + out)
        pyc_args += self.paths_to_scripts
        pyc_args += self.compilable_modules
        
        self.call_pyc(args = pyc_args, delete_resp = delete_resp, 
        executable = executable)
    
    def create_executable(self, out = None, winexe = False, 
    target_platform = None, embed = True, standalone = True, 
    mta = False, delete_resp = True, executable = IPYEXE):
        """Compile your scripts into an EXE file (.NET process 
        assembly) using pyc.py.
                
        :param str out: (optional) Specify the name of the EXE file 
        that should be created.
        :param bool winexe: (optional) Specify whether to create 
        a windows executable or to generate a console one, or a 
        console executable will be created.
        :param str target_platform: (optional) Specify the target 
        platform ("x86" or "x64") if necessary.
        :param bool embed: (optional) Specify whether to embed the 
        generated DLL into the executable.
        :param bool standalone: (optional) Specify whether to embed 
        IronPython assemblies into the executable.
        :param bool mta: (optional) Specify whether to set 
        MTAThreadAttribute (winexe). 
        :param bool delete_resp: (optional) Specify whether to delete the 
        response file after compilation or not. 
        :param str executable: (optional) Specify the name of the 
        Ironpython exectuable.
        """
        if self.compilable_modules == set():
            self.check_compilability()
        
        # pyc.pyに送る引数
        pyc_args = ["/main:" + self.paths_to_scripts[0]]
        if out is not None:
            pyc_args.append("/out:" + out)
        if winexe:
            pyc_args.append("/target:winexe")
            if mta:
                pyc_args.append("/mta")
        else:
            pyc_args.append("/target:exe")
        if target_platform in ["x86", "x64"]:
            pyc_args.append("/platform:" + target_platform)
        if embed:
            pyc_args.append("/embed")
        if standalone:
            pyc_args.append("/standalone")
        pyc_args += self.paths_to_scripts
        pyc_args += self.compilable_modules
        
        self.call_pyc(args = pyc_args, delete_resp = delete_resp, 
        executable = executable)

def compile(args):
    """Funciton for command ``compile``. It should not be used 
    directly.
    """
    mc = ModuleCompiler(paths_to_scripts = args.script)
    
    if args.target == "winexe":
        mc.create_executable(out = args.out, winexe = True, 
        target_platform = args.platform, embed = args.embed, 
        standalone = args.standalone, mta = args.mta)
    elif args.target == "exe":
        mc.create_executable(out = args.out, winexe = False, 
        target_platform = args.platform, embed = args.embed, 
        standalone = args.standalone)
    else:
        mc.create_dll(out = args.out)

def main():
    """This function will be used when ironcompiler.py is run as a script.
    """
    # トップレベル
    parser = argparse.ArgumentParser(
    description = "Compile IronPython scripts into a .NET assembly.", 
    epilog = "See '%(prog)s <command> --help' for details.")
    parser.add_argument("-v", "--version", action = "version", 
    version = "IronPyCompiler " + __version__, 
    help = "Show the version of this module.")
    subparsers = parser.add_subparsers(
    help = "Commands this module accepts.", 
    dest = "command")
    
    # サブコマンドcompile
    parser_compile = subparsers.add_parser("compile", 
    help = "Analyze scripts and compile them.")
    parser_compile.add_argument("script", nargs = "+", 
    help = "Scripts that should be compiled.")
    parser_compile.add_argument("-o", "--out", 
    help = "Output file name.")
    parser_compile.add_argument("-t", "--target",
    default = "dll", choices = ["dll", "exe", "winexe"], 
    help = "Compile scripts into dll, exe, or winexe.")
    parser_compile.add_argument("-m", "--main",
    help = "Script to be executed first.")
    parser_compile.add_argument("-p", "--platform", 
    choices = ["x86", "x64"], 
    help = "Target platform.")
    parser_compile.add_argument("-e", "--embed", 
    action = "store_true", 
    help = "Embed the generated DLL into exe/winexe.")
    parser_compile.add_argument("-s", "--standalone", 
    action = "store_true", 
    help = "Embed the IronPython assemblies into exe/winexe.")
    parser_compile.add_argument("-M", "--mta", 
    action = "store_true", 
    help = "Set MTAThreadAttribute (winexe).")
    
    args = parser.parse_args()

 
if __name__ == "__main__":
    main()
