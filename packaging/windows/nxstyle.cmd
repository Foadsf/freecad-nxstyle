@echo off
rem SPDX-License-Identifier: LGPL-2.1-or-later
rem NX-Style from a command prompt, PowerShell or a script: waits for the launcher, shows its output and returns
rem its exit code. Every option of launch_nx.py works, for example:
rem     nxstyle.cmd --smoke-test C:\r\x
rem     nxstyle.cmd --dry-run
"%~dp0NX-Style.exe" %*
exit /b %errorlevel%
