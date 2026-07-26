"""loader：在受信子进程内加载 Linux seccomp-bpf。"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import platform
from dataclasses import dataclass

from offline_companion.shell.skill_manager.seccomp.profiles import PROFILE_SYSCALLS

_AUDIT_ARCH_X86_64 = 0xC000003E
_ARCH_NR = "x86_64"
_BPF_LD = 0x00
_BPF_W = 0x00
_BPF_ABS = 0x20
_BPF_JMP = 0x05
_BPF_JEQ = 0x10
_BPF_K = 0x00
_BPF_RET = 0x06
_PR_SET_NO_NEW_PRIVS = 38
_SECCOMP_SET_MODE_FILTER = 1
_SECCOMP_RET_ALLOW = 0x7FFF0000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SYS_SECCOMP_X86_64 = 317
_SECCOMP_DATA_NR_OFFSET = 0
_SECCOMP_DATA_ARCH_OFFSET = 4
_SYSCALL_NUMBERS_X86_64: dict[str, int] = {
    "read": 0,
    "write": 1,
    "open": 2,
    "close": 3,
    "stat": 4,
    "fstat": 5,
    "lseek": 8,
    "mmap": 9,
    "mprotect": 10,
    "munmap": 11,
    "brk": 12,
    "rt_sigaction": 13,
    "rt_sigprocmask": 14,
    "rt_sigreturn": 15,
    "ioctl": 16,
    "pread64": 17,
    "readv": 19,
    "writev": 20,
    "access": 21,
    "select": 23,
    "dup": 32,
    "dup2": 33,
    "nanosleep": 35,
    "getpid": 39,
    "sendfile": 40,
    "socket": 41,
    "connect": 42,
    "accept": 43,
    "sendto": 44,
    "recvfrom": 45,
    "sendmsg": 46,
    "recvmsg": 47,
    "shutdown": 48,
    "bind": 49,
    "listen": 50,
    "getsockname": 51,
    "getpeername": 52,
    "setsockopt": 54,
    "getsockopt": 55,
    "uname": 63,
    "fcntl": 72,
    "fsync": 74,
    "fdatasync": 75,
    "truncate": 76,
    "getcwd": 79,
    "chmod": 90,
    "fchmod": 91,
    "chown": 92,
    "fchown": 93,
    "mkdir": 83,
    "rmdir": 84,
    "rename": 82,
    "unlink": 87,
    "readlink": 89,
    "sysinfo": 99,
    "getuid": 102,
    "getgid": 104,
    "geteuid": 107,
    "getegid": 108,
    "sigaltstack": 131,
    "arch_prctl": 158,
    "gettid": 186,
    "futex": 202,
    "sched_getaffinity": 204,
    "getdents64": 217,
    "set_tid_address": 218,
    "clock_gettime": 228,
    "exit": 60,
    "exit_group": 231,
    "epoll_wait": 232,
    "epoll_ctl": 233,
    "tgkill": 234,
    "openat": 257,
    "mkdirat": 258,
    "newfstatat": 262,
    "unlinkat": 263,
    "renameat": 264,
    "readlinkat": 267,
    "fchmodat": 268,
    "fchownat": 260,
    "symlinkat": 266,
    "linkat": 265,
    "pselect6": 270,
    "ppoll": 271,
    "set_robust_list": 273,
    "accept4": 288,
    "epoll_create1": 291,
    "prlimit64": 302,
    "getrandom": 318,
    "statx": 332,
    "rseq": 334,
    "ftruncate": 77,
    "poll": 7,
}


@dataclass(frozen=True)
class SeccompLoadResult:
    """摘要：描述 seccomp 装载结果。

    参数：
        applied: 是否已成功启用 seccomp。
        profile: 请求的 profile 名称。
        reason: 未启用时的原因；成功时为空字符串。
    """

    applied: bool
    profile: str
    reason: str = ""


class _SockFilter(ctypes.Structure):
    _fields_ = [
        ("code", ctypes.c_ushort),
        ("jt", ctypes.c_ubyte),
        ("jf", ctypes.c_ubyte),
        ("k", ctypes.c_uint32),
    ]


class _SockFprog(ctypes.Structure):
    _fields_ = [
        ("len", ctypes.c_ushort),
        ("filter", ctypes.POINTER(_SockFilter)),
    ]


def seccomp_runtime_supported(
    *, system_name: str | None = None, machine_name: str | None = None
) -> tuple[bool, str]:
    """摘要：判断当前运行环境是否支持第一阶段 seccomp。"""
    current_system = (system_name or platform.system()).lower()
    if current_system != "linux":
        return False, "仅 Linux 支持 seccomp-bpf"
    current_machine = (machine_name or platform.machine()).lower()
    if current_machine not in {_ARCH_NR, "amd64"}:
        return False, f"当前架构 {current_machine or 'unknown'} 暂未启用 seccomp"
    return True, ""


def load_profile(profile_name: str) -> SeccompLoadResult:
    """摘要：在受信子进程内装载 seccomp profile。

    说明：
        - 仅在 Linux x86_64 上尝试启用。
        - 非支持平台会明确降级，不阻断主流程。
        - 第一期只做启动前装载，不做运行时重校验。
        - ``OFFLINE_COMPANION_DISABLE_SECCOMP`` 不会由默认子进程环境白名单透传，仅供受控调试场景显式注入。
    """
    supported, reason = seccomp_runtime_supported()
    if not supported:
        return SeccompLoadResult(applied=False, profile=profile_name, reason=reason)
    if os.environ.get("OFFLINE_COMPANION_DISABLE_SECCOMP") == "1":
        return SeccompLoadResult(applied=False, profile=profile_name, reason="环境变量已关闭 seccomp")
    syscall_names = PROFILE_SYSCALLS.get(profile_name)
    if syscall_names is None:
        raise RuntimeError(f"未知 seccomp profile: {profile_name}")
    program = _build_filter_program(syscall_names)
    libc_path = ctypes.util.find_library("c")
    if not libc_path:
        raise RuntimeError("未找到 libc，无法装载 seccomp")
    libc = ctypes.CDLL(libc_path, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    libc.syscall.argtypes = [
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.POINTER(_SockFprog),
    ]
    libc.syscall.restype = ctypes.c_long
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        err = ctypes.get_errno()
        raise RuntimeError(f"prctl(PR_SET_NO_NEW_PRIVS) 失败: errno={err}")
    if libc.syscall(_SYS_SECCOMP_X86_64, _SECCOMP_SET_MODE_FILTER, 0, ctypes.byref(program)) != 0:
        err = ctypes.get_errno()
        raise RuntimeError(f"seccomp(SECCOMP_SET_MODE_FILTER) 失败: errno={err}")
    return SeccompLoadResult(applied=True, profile=profile_name)


def _build_filter_program(syscall_names: tuple[str, ...]) -> _SockFprog:
    filters = [
        _stmt(_BPF_LD | _BPF_W | _BPF_ABS, _SECCOMP_DATA_ARCH_OFFSET),
        _jump(_BPF_JMP | _BPF_JEQ | _BPF_K, _AUDIT_ARCH_X86_64, 1, 0),
        _stmt(_BPF_RET | _BPF_K, _SECCOMP_RET_KILL_PROCESS),
        _stmt(_BPF_LD | _BPF_W | _BPF_ABS, _SECCOMP_DATA_NR_OFFSET),
    ]
    for syscall_name in syscall_names:
        syscall_number = _SYSCALL_NUMBERS_X86_64.get(syscall_name)
        if syscall_number is None:
            raise RuntimeError(f"seccomp profile 包含未知 syscall: {syscall_name}")
        filters.append(_jump(_BPF_JMP | _BPF_JEQ | _BPF_K, syscall_number, 0, 1))
        filters.append(_stmt(_BPF_RET | _BPF_K, _SECCOMP_RET_ALLOW))
    filters.append(_stmt(_BPF_RET | _BPF_K, _SECCOMP_RET_ERRNO | errno.EPERM))
    filter_array = (_SockFilter * len(filters))(*filters)
    program = _SockFprog(len=len(filters), filter=filter_array)
    program._filter_array = filter_array
    return program


def _stmt(code: int, k: int) -> _SockFilter:
    return _SockFilter(code=code, jt=0, jf=0, k=k)


def _jump(code: int, k: int, jt: int, jf: int) -> _SockFilter:
    return _SockFilter(code=code, jt=jt, jf=jf, k=k)
