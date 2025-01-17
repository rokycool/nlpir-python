# coding=utf-8
import os
import logging
import sys
import platform
import ctypes
import typing
import functools
import threading
from abc import ABC
from ctypes import c_int
from nlpir import PACKAGE_DIR
from nlpir.exception import NLPIRException

# All available encoding, according to the header(.h) file
# 根据对应头文件,NLPIR可设置的编码格式
#: 如果是各种编码混合，设置为-1，系统自动检测，并内部转换。会多耗费时间，不推荐使用
UNKNOWN_CODE = -1
#: 默认支持GBK编码
GBK_CODE = 0
#: UTF8编码
UTF8_CODE = 1
#: BIG5编码
BIG5_CODE = 2
#: GBK编码，里面包含繁体字
GBK_FANTI_CODE = 3
#: UTF8编码
UTF8_FANTI_CODE = 4

# Output format
OUTPUT_FORMAT_XML = 0  #: EyeChecker 使用的
OUTPUT_FORMAT_SHARP = 0  #: 正常的字符串按照#链接的输出新词结果
OUTPUT_FORMAT_JSON = 1  #: 正常的JSON字符串输出新词结果
OUTPUT_FORMAT_EXCEL = 2  #: 正常的CSV字符串输出新词结果,保存为csv格式即可采用Excel打开


class NLPIRBase(ABC):
    """
    抽象类,作为各种NLPIR组件的基类,提供加载DLL等功能,大部分代码借鉴于pynlpir项目
    Provides a low-level Python interface for NLPIR.
    Most of code in this model is copy/inspired from pynlpir

    继承此类必须实现虚方法,实现对应不同组件的初始化和销毁动作.
    为了使得类可以加载对应DLL,需要制定DLL名称,名称符合一般的操作系统对于动态链接库的命名规则:

    - linux: lib{Dll_name}32.so lib{Dll_name}64.so
    - macOS: lib{Dll_name}darwin.so 此处macOS与linux动态库命名方式一致,为了区分故加入darwin
    - windows: {Dll_name}32.dll, {Dll_name}64.dll

    :param int encode: An encoding code provide from NLPIR's header , defined in this package
    :param str lib_path: The location of custom dynamic link library, None if use build-in lib
    :param str data_path: The location of custom Data directory, None if use build-in Data directory.
        Can bu used in custom dictionary but dont want to change the build-in Data directory
    :param str license_code: for license
    :raises NLPIRException: Init the dynamic link library fail, can get an error message from dll
    """
    #: A logger using for all native nlpir functions
    logger = logging.getLogger('nlpir.naive')

    encode_map = {
        UNKNOWN_CODE: "utf-8",
        GBK_CODE: "gbk",
        UTF8_CODE: "utf-8",
        BIG5_CODE: "big5",
        GBK_FANTI_CODE: "gbk",
        UTF8_FANTI_CODE: "utf-8"
    }

    #: use it if want load DLL in other mode
    load_mode = None

    #: lazy load DLL ,not supported for window, will be None on OS: windows
    RTLD_LAZY = os.RTLD_LAZY if hasattr(os, "RTLD_LAZY") else None

    __instance_lock__ = threading.Lock()

    # 函数泛型, 用于支持在使用装饰器时, 目标函数获取正确的参数值
    __T__ = typing.TypeVar("__T__", bound=typing.Callable[..., typing.Any])

    @staticmethod
    def byte_str_transform(func: __T__) -> __T__:
        """
        一个包装器,作为装饰器使用,会自动将使用装饰器的函数的参数中的str转换为bytes, 在返回值中将bytes转换为str

        此包装器只能在这个类的子类函数成员中使用,目的是简化动态链接库调用的编码转换问题

        A wraps that automatically detect str parameter , transform to bytes
        and transform return value from bytes to str if it's bytes.

        This function is used for call the function from dynamic lib.
        This function can only use in NLPIRBase's sub class

        :param func: function
        """

        @functools.wraps(func)
        def wraps(self, *args, **kwargs):
            args = list(args)
            for i, arg in enumerate(args):
                if isinstance(arg, str):
                    args[i] = arg.encode(self.encode)
            for k in kwargs:
                if isinstance(kwargs[k], str):
                    kwargs[k] = kwargs[k].encode(self.encode)
            return_value = func(self, *args, **kwargs)
            if isinstance(return_value, bytes):
                return return_value.decode(self.encode, errors="ignore")
            elif isinstance(return_value, tuple):
                return_value = list(return_value)
                for i, item in enumerate(return_value):
                    if isinstance(item, bytes):
                        return return_value[i].decode(self.encode)
                return tuple(return_value)
            else:
                return return_value

        return wraps

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, '__instance__'):
            with cls.__instance_lock__:
                if not hasattr(cls, '__instance__'):
                    cls.__instance__ = object.__new__(cls)
        return cls.__instance__

    def __init__(
            self,
            encode: int = UTF8_CODE,
            lib_path: typing.Optional[int] = None,
            data_path: typing.Optional[str] = None,
            license_code: str = ''
    ):
        if hasattr(self, "lib_nlpir"):
            logging.debug(f"{self} use singleton, skip init")
            return
        self.LIB_DIR = os.path.join(PACKAGE_DIR, 'lib') if lib_path is None else lib_path
        self.lib_nlpir, self.lib_path = self.load_library(platform.uname())
        self.encode: str = self.encode_map[encode]
        self.encode_nlpir = encode
        self.data_path = PACKAGE_DIR if data_path is None else data_path
        if self.init_lib(self.data_path, self.encode_nlpir, license_code) == 0:
            error_msg = self.get_last_error_msg()
            self.logger.error(error_msg)
            raise NLPIRException(error_msg)

    def __del__(self):
        return self.exit_lib()

    @property
    def dll_name(self):
        """
        :return: The name of dynamic link library, more info in class description
        """
        raise NotImplementedError

    def init_lib(self, data_path: str, encode: int, license_code: str) -> int:
        """
        所有子类都需要实现此方法用于类初始化实例时调用, 由于各个库对应初始化不同,故改变此函数名称

        :param str data_path: the location of Data , Data文件夹所在位置
        :param encode: encode code define in NLPIR
        :param str license_code: license code for unlimited usage. common user ignore it
        :return: 1 success 0 fail
        """
        raise NotImplementedError

    def exit_lib(self) -> bool:
        """
        所有子类都需要实现此方法用于类析构(销毁)实例时调用, 由于各个库对应初始化不同,故改变此函数名称
        """
        raise NotImplementedError

    def get_dll_path(self, uname: platform.uname_result, lib_dir: str, is_64bit: bool) -> str:
        """
        :param platform.uname_result uname: The platform identifier for the user's system.
        :param str lib_dir: path to lib
        :param bool is_64bit: is 64bit or not
        :return: the abspath of dll
        :rtype: str
        """

        def get_dll_prefix(paths, prefix, suffix):
            lib_path = lib_dir
            for path in paths:
                lib_path = os.path.join(lib_path, path)
            return os.path.join(lib_path, prefix + self.dll_name + suffix)

        # TODO need to know the arch for windows if there is an arm processor
        # in Windows machine is AMD64, linux is x86_64 as well
        if uname.system.startswith('Win'):
            if is_64bit:
                lib = get_dll_prefix(["win", "lib64"], "", "64")
            else:
                lib = get_dll_prefix(["win", "lib32"], "", "32")
            # add search path to fix the libcurl.dll not found bug on python <3.8
            # same bugfix for python3.6, 3,7
            if sys.version_info <= (3, 8):
                os.environ["PATH"] += ";" + os.path.dirname(lib)
        elif uname.system.startswith('Linux'):
            if platform.machine().startswith("x86"):
                if is_64bit:
                    lib = get_dll_prefix(["linux", "x86", "lib64"], "lib", "64.so")
                else:
                    lib = get_dll_prefix(["linux", "x86", "lib32"], "lib", "32.so")
            elif platform.machine().startswith("aarch64"):
                lib = get_dll_prefix(["linux", "aarch64"], "lib", ".so")
            else:
                raise RuntimeError(f"Platform with system:{uname.system} arch:{uname.machine} is not supported.")
        elif uname.system.startswith("Darwin"):
            lib = get_dll_prefix(["darwin"], "lib", ".so")
            # lib = get_dll_prefix("lib", ".dylib")
        else:
            raise RuntimeError(f"Platform with system:{uname.system} arch:{uname.machine} is not supported.")
        self.logger.debug("Using {} file for {}".format(lib, platform))
        return lib

    def load_library(
            self,
            uname: platform.uname_result,
            is_64bit: typing.Optional[bool] = None,
            lib_dir: typing.Optional[str] = None
    ) -> typing.Tuple[ctypes.CDLL, str]:
        """Loads the NLPIR library appropriate for the user's system.
        This function is called automatically when create a instance.

        :param platform.uname_result uname: The platform identifier for the user's system.
        :param bool is_64bit: Whether or not the user's system is 64-bit.
        :param str lib_dir: The directory that contains the library files
            (defaults to :data:`LIB_DIR`).
        :return: a dynamic lib object
        :rtype: tuple(ctypes.CDLL, str)
        :raises RuntimeError: The user's platform is not supported by NLPIR.
        """
        if lib_dir is None:
            lib_dir = self.LIB_DIR
        self.logger.debug("Loading NLPIR library file from '{}'".format(lib_dir))
        if is_64bit is None:
            is_64bit = sys.maxsize > 2 ** 32
        lib = self.get_dll_path(uname, lib_dir, is_64bit)
        if self.load_mode is not None:

            lib_nlpir = ctypes.CDLL(lib, mode=self.load_mode)
        else:
            lib_nlpir = ctypes.cdll.LoadLibrary(lib)
        self.logger.debug("{} library file '{}' loaded.".format(self.dll_name, lib))
        return lib_nlpir, lib

    def get_func(
            self,
            name: str,
            argtypes: typing.Optional[list] = None,
            restype: typing.Any = c_int
    ) -> typing.Callable:
        """Retrieves the corresponding NLPIR function.

        :param str name: The name of the NLPIR function to get.
        :param list argtypes: A list of :mod:`ctypes` data types that correspond
            to the function's argument types.
        :param ctypes restype: A :mod:`ctypes` data type that corresponds to the
            function's return type (only needed if the return type isn't
            :class:`ctypes.c_int`).
        :return: The exported function. It can be called like any other Python
            callable.
        :rtype: Callable Function
        """
        self.logger.debug("Getting NLPIR API function: 'name': '{}', 'argtypes': '{}',"
                          " 'restype': '{}'.".format(name, argtypes, restype))
        func = getattr(self.lib_nlpir, name)
        if argtypes is not None:
            func.arg_types = argtypes
        if restype is not c_int:
            func.restype = restype
        self.logger.debug("NLPIR API function '{}' retrieved.".format(name))
        return func

    def get_last_error_msg(self) -> str:
        """
        对应每个组件获取异常信息的函数
        """
        raise NotImplementedError
