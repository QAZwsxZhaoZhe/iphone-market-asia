from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT, SCHEDULE_TASK_NAME


class SchedulerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduleInfo:
    task_name: str
    start_boundary: str | None
    start_when_available: bool
    wake_to_run: bool
    command: str | None
    arguments: str | None
    working_directory: str | None


def pythonw_executable() -> Path:
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def build_task_xml(
    *,
    task_name: str = SCHEDULE_TASK_NAME,
    start_time: str = "08:00",
    project_root: Path = PROJECT_ROOT,
    executable: Path | None = None,
) -> str:
    executable = executable or pythonw_executable()
    start_boundary = _start_boundary(start_time)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>每天 08:00 采集香港二手 iPhone 报价，生成日报，并在端口空闲时启动本地看板。</Description>
    <URI>\\{_xml(task_name)}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{_xml(start_boundary)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT6H</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT15M</Interval>
      <Count>2</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml(str(executable))}</Command>
      <Arguments>-m iphone_market collect --headed --start-dashboard</Arguments>
      <WorkingDirectory>{_xml(str(project_root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def install_schedule(
    *,
    task_name: str = SCHEDULE_TASK_NAME,
    start_time: str = "08:00",
    project_root: Path = PROJECT_ROOT,
) -> ScheduleInfo:
    _require_windows()
    _validate_time(start_time)
    xml = build_task_xml(
        task_name=task_name,
        start_time=start_time,
        project_root=project_root,
    )
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-16",
            suffix=".xml",
            delete=False,
        ) as handle:
            handle.write(xml)
            temp_path = Path(handle.name)
        completed = subprocess.run(
            ["schtasks.exe", "/Create", "/TN", task_name, "/XML", str(temp_path), "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            raise SchedulerError(completed.stderr.strip() or completed.stdout.strip())
        return show_schedule(task_name)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def show_schedule(task_name: str = SCHEDULE_TASK_NAME) -> ScheduleInfo:
    _require_windows()
    completed = subprocess.run(
        ["schtasks.exe", "/Query", "/TN", task_name, "/XML"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SchedulerError(completed.stderr.strip() or completed.stdout.strip())
    return parse_task_xml(completed.stdout, task_name=task_name)


def remove_schedule(task_name: str = SCHEDULE_TASK_NAME) -> None:
    _require_windows()
    completed = subprocess.run(
        ["schtasks.exe", "/Delete", "/TN", task_name, "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SchedulerError(completed.stderr.strip() or completed.stdout.strip())


def run_schedule_now(task_name: str = SCHEDULE_TASK_NAME) -> None:
    _require_windows()
    completed = subprocess.run(
        ["schtasks.exe", "/Run", "/TN", task_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SchedulerError(completed.stderr.strip() or completed.stdout.strip())


def parse_task_xml(xml_text: str, task_name: str = SCHEDULE_TASK_NAME) -> ScheduleInfo:
    namespace = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    root = ET.fromstring(xml_text)
    start = root.findtext(".//t:StartBoundary", namespaces=namespace)
    start_when_available = root.findtext(".//t:StartWhenAvailable", namespaces=namespace)
    wake_to_run = root.findtext(".//t:WakeToRun", namespaces=namespace)
    command = root.findtext(".//t:Exec/t:Command", namespaces=namespace)
    arguments = root.findtext(".//t:Exec/t:Arguments", namespaces=namespace)
    working_directory = root.findtext(".//t:Exec/t:WorkingDirectory", namespaces=namespace)
    registered_name = root.findtext(".//t:RegistrationInfo/t:URI", namespaces=namespace)
    if registered_name:
        registered_name = registered_name.strip().lstrip("\\")
    return ScheduleInfo(
        task_name=registered_name or task_name,
        start_boundary=start,
        start_when_available=(start_when_available or "").lower() == "true",
        wake_to_run=(wake_to_run or "").lower() == "true",
        command=command,
        arguments=arguments,
        working_directory=working_directory,
    )


def _start_boundary(start_time: str) -> str:
    from datetime import date

    return f"{date.today().isoformat()}T{start_time}:00"


def _validate_time(value: str) -> None:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError("时间格式应为 HH:MM")
    hour, minute = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("时间范围无效")


def _xml(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _require_windows() -> None:
    if os.name != "nt":
        raise SchedulerError("定时任务安装仅支持 Windows。")
