"""profiles：seccomp profile 选择与白名单定义。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from offline_companion.shell.skill_manager.manifest import SkillManifest

SECCOMP_PROFILE_COMPUTE = "compute"
SECCOMP_PROFILE_FILE_IO = "file_io"
SECCOMP_PROFILE_NETWORK = "network"

PERM_FILE_ACCESS = "file_access"
PERM_NETWORK_EGRESS = "network_egress"
PERM_CLOUD_INFERENCE = "cloud_inference"

# 说明：
# - ``open/openat`` 保留在 base，是 Python 运行时加载脚本与动态 import 的硬依赖。
# - 因此 Sprint 8 的 compute profile 允许文件读写；路径级文件访问控制由 Landlock（Sprint 9+）补强。
# - ``clone/fork/vfork`` 不在任何 profile 中，这是设计意图：threading 不可用，但 asyncio 不受影响。
_BASE_SYSCALLS: tuple[str, ...] = (
    "read",
    "write",
    "open",
    "close",
    "fstat",
    "lseek",
    "mmap",
    "mprotect",
    "munmap",
    "brk",
    "rt_sigaction",
    "rt_sigprocmask",
    "rt_sigreturn",
    "ioctl",
    "pread64",
    "readv",
    "writev",
    "access",
    "dup",
    "dup2",
    "nanosleep",
    "getpid",
    "sendfile",
    "shutdown",
    "fcntl",
    "fsync",
    "fdatasync",
    "getcwd",
    "uname",
    "sysinfo",
    "getuid",
    "getgid",
    "geteuid",
    "getegid",
    "sigaltstack",
    "arch_prctl",
    "gettid",
    "futex",
    "sched_getaffinity",
    "set_tid_address",
    "clock_gettime",
    "exit",
    "exit_group",
    "tgkill",
    "openat",
    "newfstatat",
    "readlink",
    "readlinkat",
    "getdents64",
    "statx",
    "set_robust_list",
    "prlimit64",
    "getrandom",
    "rseq",
)

# 说明：
# - ``chown/fchown/fchownat`` 不是提权路径；非 root 进程只能修改到自身 uid/gid 允许的范围。
# - file_io 在 compute 之上补充文件管理与写入类 syscall，形成真正有意义的权限增量。
_FILE_IO_EXTRA_SYSCALLS: tuple[str, ...] = (
    "stat",
    "mkdir",
    "mkdirat",
    "rename",
    "renameat",
    "unlink",
    "unlinkat",
    "rmdir",
    "ftruncate",
    "truncate",
    "chmod",
    "fchmod",
    "fchmodat",
    "chown",
    "fchown",
    "fchownat",
    "linkat",
    "symlinkat",
)

_NETWORK_EXTRA_SYSCALLS: tuple[str, ...] = (
    "socket",
    "connect",
    "bind",
    "listen",
    "accept",
    "accept4",
    "getsockname",
    "getpeername",
    "setsockopt",
    "getsockopt",
    "recvfrom",
    "sendto",
    "recvmsg",
    "sendmsg",
    "poll",
    "select",
    "pselect6",
    "ppoll",
    "epoll_create1",
    "epoll_ctl",
    "epoll_wait",
)

PROFILE_SYSCALLS: dict[str, tuple[str, ...]] = {
    SECCOMP_PROFILE_COMPUTE: _BASE_SYSCALLS,
    SECCOMP_PROFILE_FILE_IO: _BASE_SYSCALLS + _FILE_IO_EXTRA_SYSCALLS,
    SECCOMP_PROFILE_NETWORK: _BASE_SYSCALLS + _FILE_IO_EXTRA_SYSCALLS + _NETWORK_EXTRA_SYSCALLS,
}


def select_seccomp_profile(manifest: SkillManifest) -> str:
    """摘要：按 Skill 权限选择最小 seccomp profile。"""
    # 说明：调用方（A2 策略层）需保证 B/C 层 Skill 不声明 ``network_egress`` / ``cloud_inference``。
    permissions = set(manifest.permissions)
    if PERM_NETWORK_EGRESS in permissions or PERM_CLOUD_INFERENCE in permissions:
        return SECCOMP_PROFILE_NETWORK
    if PERM_FILE_ACCESS in permissions:
        return SECCOMP_PROFILE_FILE_IO
    return SECCOMP_PROFILE_COMPUTE


def resolve_runtime_seccomp_profile(manifest: SkillManifest) -> str:
    """??????????????? seccomp profile?"""
    profile = select_seccomp_profile(manifest)
    if manifest.entrypoint.type == "local_api":
        return SECCOMP_PROFILE_NETWORK
    return profile
