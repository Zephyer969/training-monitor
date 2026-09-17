# Training Monitor

作者：Zephyer

炼丹台（Training Monitor）是一个轻量级深度学习训练监控工具。它由三部分组成：

- 服务器端监控服务：运行在训练服务器上，读取训练日志或接收训练脚本上报。
- 电脑端像素面板：在你的电脑上通过 SSH 读取训练服务器，自动识别多张 GPU 和多个训练任务。
- 安卓 App“炼丹台”：只连接电脑端像素面板的只读同步接口，实时查看训练进度、当前指标、最好指标、最好轮次和预计剩余时间。

当前版本适合这些场景：

- OpenMMLab / MMEngine：自动读取 `.log`、`.json`、`.jsonl` 里的 `loss`、`mIoU`、`BBox mAP`、`NDS`、`PQ`、`Top1 Acc`、`PCK` 等常见指标。
- YOLO / Ultralytics：自动读取 `results.csv` 里的 `mAP`。
- 其他 PyTorch 项目：可以用通用 HTTP 接口或 Python helper 主动上报。
- 任意服务器：只要电脑能通过 SSH 读取它，手机就不需要直接访问服务器或保存服务器 SSH 信息。

> 说明：不同深度学习框架没有完全统一的日志格式，所以不承诺百分百自动识别所有项目。这个工具的原则是：OpenMMLab / YOLO 常见日志自动识别，特殊项目用统一接口接入。

新版 App 会缓存最后一次成功同步的数据。服务器关机、训练完成后断网、临时网络不稳定时，手机端仍然能看到最后一次同步到本地的训练进度和曲线。

安全默认值：服务端接口和电脑端本地同步接口都必须使用 token；App 会加密保存本地同步 Token；安装脚本默认只从 GitHub 官方 Release 下载服务端安装包，镜像下载需要你手动开启。

[查看炼丹台完整隐私政策](https://github.com/Zephyer969/training-monitor/blob/main/PRIVACY.md)

完整中文安装、配置、启动、手机同步、安全和故障排查说明：
[USER_GUIDE.zh-CN.md](docs/USER_GUIDE.zh-CN.md)

## 1. 快速开始

推荐先用 pip 安装服务器端。安装后会像 `tensorboard` 一样在当前 Python/Conda 环境里提供 `training-monitor` 命令。学校服务器或国内机房如果直连 GitHub 很慢，优先用镜像 wheel：

```bash
python3 -m pip install --upgrade "https://gh-proxy.com/https://github.com/Zephyer969/training-monitor/releases/download/v0.7.30/xunji_training_monitor-0.7.30-py3-none-any.whl"
training-monitor start
training-monitor connection
```

如果镜像不可用，可以换一个镜像前缀：

```bash
python3 -m pip install --upgrade "https://gh.llkk.cc/https://github.com/Zephyer969/training-monitor/releases/download/v0.7.30/xunji_training_monitor-0.7.30-py3-none-any.whl"
```

如果你的服务器能直接访问 GitHub，也可以安装源码包：

```bash
python3 -m pip install --upgrade https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-server.tar.gz
```

注意：`pip -i 清华源` 只加速 PyPI 依赖，不会加速 `https://github.com/...` 这种文件下载。

安装成功后直接运行：

```bash
training-monitor start
training-monitor connection
```

如果出现 `training-monitor: command not found`，说明 pip 已经安装成功，但当前 shell 没加载命令目录。直接运行：

```bash
python3 -m monitorctl_py fix-path
export PATH="$HOME/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:$PATH"
```

如果服务器没有配置 pip，或者你想直接一键安装，在训练服务器上执行。安装脚本会优先把包安装到当前 Python 环境；如果当前环境不能安装，才会自动回退到独立运行目录：

```bash
curl -fL https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-install-server.sh | bash
```

这个命令不依赖 `raw.githubusercontent.com`。如果服务器访问 GitHub Release 很慢，可以手动指定服务端安装包地址。注意：镜像下载更快，但需要你信任这个镜像源。

```bash
curl -fL "https://gh-proxy.com/https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-install-server.sh" \
  | TRAINING_MONITOR_GITHUB_PROXY="https://gh-proxy.com" bash
```

安装完成后查看连接信息：

```bash
training-monitor connection
```

如果需要诊断安装状态：

```bash
training-monitor doctor
```

如果脚本回退到独立运行目录，root 用户默认会同时创建：

```text
/usr/local/bin/training-monitor
```

你会看到类似输出：

```text
server port: 6006
backend url: http://xxx.xxx.xxx.xxx:6006
access token: xxxxxxxxxxxxxxxxxxxxxxxx
```

然后在手机上安装 APK。新版推荐的链路是“服务器 ← SSH ← 电脑端像素面板 ← Wi-Fi/VPN ← 手机”：

[下载最新版 APK](https://github.com/Zephyer969/training-monitor/releases/latest)

打开 App 后不要填写训练服务器的 URL。请按第 6 节配置“本地电脑面板”地址和 Token。

不要把服务器端 `access token` 或电脑端本地同步 Token 发给别人。如果怀疑服务器端 token 泄露，在服务器上执行：

```bash
training-monitor rotate-token
```

服务器端 token 只供服务器 API 使用；手机 App 使用的是电脑端“手机同步”弹窗里的本地同步 Token。

## 2. 服务器安装

### 2.1 基本要求

服务器需要有：

- Linux
- Python 3
- `curl` 或 `wget`
- 手机能访问到服务器开放出来的后端地址

推荐使用 pip 安装到当前 Python/Conda 环境。安装后命令入口和 `tensorboard` 类似，直接运行 `training-monitor start`、`training-monitor connection` 即可。

一键安装脚本也会优先执行环境安装；如果服务器的 Python 环境被系统限制、不能写入 site-packages，脚本才会自动创建独立运行目录作为兜底。你也可以显式指定：

```bash
TRAINING_MONITOR_INSTALL_MODE=env bash training-monitor-install-server.sh   # 只允许安装到当前环境
TRAINING_MONITOR_INSTALL_MODE=venv bash training-monitor-install-server.sh  # 强制使用独立运行目录
```

### 2.2 状态和日志位置

Python 包会安装到当前环境；训练状态、token、日志和配置文件仍会放到一个独立目录，方便升级包时保留数据。

如果你是 `root` 用户，并且服务器存在 `/root/autodl-tmp`，默认安装到：

```text
/root/autodl-tmp/training-monitor
```

否则默认安装到：

```text
~/.training-monitor
```

### 2.3 自定义安装仓库

如果你 fork 了这个项目，可以这样安装自己的仓库：

```bash
TRAINING_MONITOR_REPO_SLUG="你的用户名/training-monitor" \
curl -fL https://github.com/你的用户名/training-monitor/releases/latest/download/training-monitor-install-server.sh | bash
```

## 3. 服务器配置

第一次安装后建议执行：

```bash
training-monitor setup
```

它会依次询问几个配置：

```text
Port [6006]:
Public URL [自动检测到的地址]:
Log roots [/root/mmdetection* /root/mmdetection3d* /root/mmdet3d* /root/mmsegmentation* /root/mmclassification* /root/mmpretrain* /root/mmselfsup* /root/mmyolo* /root/mmpose* /root/mmrotate* /root/mmocr* /root/mmaction* /root/mmaction2* /root/mmagic* /root/mmediting* /root/mmgeneration* /root/mmtracking* /root/mmtrack* /root/mmrazor* /root/mmhuman3d* /root/mmfewshot* /root/mmdeploy* /root/work_dirs /root/*/work_dirs /root/autodl-tmp/*/work_dirs /root/workspace/*/work_dirs /root/autodl-tmp /root/workspace /root/runs]:
Log type auto/openmmlab/yolo [auto]:
Auto watch 1/0 [1]:
```

一般情况下直接回车即可。

如果自动检测到的公网地址不对，可以手动设置：

```bash
training-monitor config set PUBLIC_URL https://你的公网域名
training-monitor restart
```

如果你的训练日志不在默认目录，可以设置日志扫描目录：

```bash
training-monitor config set LOG_ROOTS "/root/project1 /root/project2/runs /root/autodl-tmp"
training-monitor restart
```

查看当前配置：

```bash
training-monitor config show
```

配置文件位置：

```bash
training-monitor config path
```

## 4. 常用命令

下面都写成 `training-monitor ...`。如果服务器提示 `training-monitor: command not found`，把前缀换成 `python3 -m monitorctl_py ...`，或者先执行 `python3 -m monitorctl_py fix-path`。

启动服务：

```bash
training-monitor start
```

停止服务：

```bash
training-monitor stop
```

重启服务：

```bash
training-monitor restart
```

查看当前训练状态：

```bash
training-monitor status
```

查看手机连接信息：

```bash
training-monitor connection
```

查看 token：

```bash
training-monitor token
```

重新生成 token：

```bash
training-monitor rotate-token
```

查看后端和自动检测日志：

```bash
training-monitor logs
```

## 5. 电脑端像素炼丹台

### 导师桌面炼丹台

Windows 可从 CMD 或 PowerShell 启动桌面窗口，显示确认版导师角色：

```powershell
# 电脑端直连模式只需要 Pillow；Tk 通常随 Windows Python 一起提供
py -3 -m pip install "pillow>=10.0"
py -3 -m monitorctl_py desktop --demo
```

如果你已经把整个 Python 包安装到当前环境，也可以使用 `py -3 -m pip install -e ".[desktop]"`。

演示模式使用明确标注的模拟数据，可切换 0–32 张显卡和训练状态。
连接实际训练服务器：

```powershell
training-monitor desktop --url http://服务器地址:6006 --token 你的Token
```

### 一键打开并自动发现正在训练的任务

推荐在项目目录执行一次：

```powershell
Copy-Item monitor.config.example.json monitor.config.json
```

然后只修改 `monitor.config.json` 里的 `ssh` 一行，例如 `user@服务器地址`，
双击 `start-monitor.vbs` 即可无黑色 CMD 窗口启动；这个配置文件已被 Git 忽略，不会把你的服务器地址提交到仓库；
也不会保存 SSH 密码，密码仍由 SSH 自己提示输入。没有配置文件时，启动脚本会临时询问一次服务器地址。

如果需要查看启动错误或临时传入服务器地址，再使用 `start-monitor.cmd`；它是排错入口，
不是桌面窗口运行所必需的组件。

也可以直接运行 `training-monitor desktop --ssh 用户@服务器`，
或用 `start-monitor.cmd 用户@其他服务器` 临时切换目标。
使用系统 SSH 登录配置；需要密码时在启动终端输入，不保存密码。
首次连接新主机时按 SSH 提示核对主机指纹。

如果没有 SSH 公钥，不需要先配置公钥。电脑端安装完成后，在本地 PowerShell 或 CMD
执行一次下面两条命令，重新打开终端，然后可以直接运行：

```powershell
py -3 -m pip install -e ".[desktop]"
py -3 -m monitorctl_py fix-path
```

```powershell
start train_mot user@服务器地址
```

这会启动本地像素面板，并在新开的连接窗口中显示系统 SSH 的密码提示；密码只交给
OpenSSH 使用，不保存到项目文件。`user@服务器地址` 是本次明确指定的目标，
不会自动读取本地 SSH 配置来选择服务器。若不想打开新窗口，也可以直接运行
`train_mot user@服务器地址`。

直接连接模式自动读取物理显卡、GPU 进程和正在训练的 OpenMMLab 日志，
通过进程打开的日志文件、`--work-dir` 和配置路径匹配实验。DDP 多进程按同一日志合并，
GPU 绑定来自 `nvidia-smi` 的真实 PID/UUID。关闭界面会关闭此 SSH 采集连接。
无需服务器安装监控依赖、开放 API 端口或手工建隧道；采集代码仅在服务器内存执行。
服务器只需要 Python 3.8+、可读 `/proc` 和 `nvidia-smi`；不需要安装本项目、FastAPI、Uvicorn，
也不需要开放 API 端口或创建隧道。默认 `remote_python: auto` 会按 `python3`、`python` 顺序选择可用解释器。
因此把项目复制到另一台服务器时，通常只需改 SSH 地址；如果训练日志不在自动发现范围，再补充 `log_roots`。

特殊日志目录可追加 `--log-root /path/to/work_dirs`，自定义 Python 用 `--remote-python /path/to/python`；
这些参数也可以写入 `monitor.config.json`。直接连接模式启动时会把采集器压缩后通过 SSH 临时送到内存执行，
服务器不留下监控文件、缓存或连接日志。
自动发现目前针对 `train.py`、`training.py` 或 `.train` 入口和 OpenMMLab 文本/JSONL 日志；
其他训练框架需要兼容日志解析器或继续使用已有上报 API。

面板固定显示 **Loss** 和 **mIoU**，mIoU 保留最近验证值并标注验证轮次。
尚未验证时显示等待状态，不用 Loss 代替。顶部 TOTAL 为整个训练进度，详情条为当前轮次步数进度。
训练历史启动时读取一次，随后增量读取新日志；每张显卡卡片同时显示任务与硬件状态。

也可通过 `TRAINING_MONITOR_TOKEN` 环境变量提供 Token。
窗口自动读取服务器 GPU 清单，适配多模型共享显卡、多卡训练与空闲卡；
任务多时可滚动。网络请求在后台执行，断线会提示并自动重试，保留最后数据。
界面按像素炼丹监控台布局：顶部任务表，中央 Loss/指标曲线与导师炼丹房，
下方每张显卡一位助手，底部硬件状态。点击任务行或助手卡片切换选中任务，
也可使用上下方向键。显卡超过四张时向下滚动查看。
任务表会把训练中、验证中和保存中的任务排在前面，暂停或停滞任务居中，
已完成、已停止和异常任务稳定放到后面；终止任务仍会保留，只有点击红色像素 `×` 才会手动隐藏。
底部助手不是复用同一张图：内置 8 个不同身份、每个身份 2 帧动作，并按 GPU 卡错峰播放；
超过 8 张显卡时自动使用镜像和颜色变体，仍保持每张卡的角色有区别。
选中任务后点击顶部 `F2 / 重命名`，把相近的实验标成 `unit1`、`unit2`；
名称只保存在查看电脑的 `monitor.names.json`，不会写回服务器日志。训练完成、停止或异常的任务
会继续保留，任务旁的红色像素 `×` 需要你手动点击后才会从面板隐藏；如果同一个任务 ID 重新训练，
它会自动恢复显示。
导师使用固定原图，显示时去除背景且不改动脸部像素；大炼丹炉会以统一尺寸循环显示搅拌、加入药水、
投放药材三组连续动作，不再使用扇火或取样动作，工作状态有放慢的轻微动画。
训练状态使用独立的四帧主搅拌动作，搅拌棒会从丹炉左侧经过中央移动到右侧再返回；
运行时会统一动作帧的有效尺寸和脚底基线，避免导师忽大忽小。
窗口顶部带有像素化应用图标和工作区标题；按住 `Ctrl` 滚动鼠标滚轮可等比例放大或缩小，
`Ctrl + 0` 恢复默认比例，`Ctrl + +` / `Ctrl + -` 可微调缩放。
使用 `TrainingMonitor.log(..., loss=0.12, step=50, total_steps=100)` 上报 Loss 和步数。
没有上报步数时进度条使用 Epoch 进度；没有历史数据时显示等待提示，不填充模拟曲线。
桌面功能需要 Python Tk（Windows 官方安装一般自带）。

### 5.1 手机同步：手机只连接本地电脑

桌面窗口启动后会自动开启只读同步接口，默认监听电脑的 `8765` 端口。点击窗口顶部的 `手机同步`，复制其中的地址和本地同步 Token 到手机 App。

- 手机和电脑在同一 Wi-Fi：填写电脑的局域网地址，例如 `http://192.168.1.20:8765`。
- 人在外面查看：让电脑和手机加入同一个 Tailscale/WireGuard 网络，填写电脑的 VPN 地址，例如 `http://100.100.12.8:8765`。电脑必须保持开机、桌面面板运行并能继续 SSH 到训练服务器。
- 不要填写 `127.0.0.1`：它只代表手机自己；也不要把训练服务器地址或 SSH 密码填入 App。
- 如果同一 Wi-Fi 仍无法连接，只需在 Windows 防火墙中允许 `8765/TCP` 的“专用网络”入站访问，不要把端口暴露到公网。

手机端拿到的是电脑当前显示的快照，包含多个训练任务、GPU 使用率、Loss、mIoU、Epoch、进度和历史曲线；接口是只读的，手机不能控制训练或修改服务器。

如果怀疑手机 Token 泄露，可以打开桌面窗口的“手机同步”，点击“重置 Token”。确认后旧 Token 会立即失效，新的 Token 会写入本地令牌文件；再把新 Token 填入手机 App 即可。建议保持配置文件中的 `local_token` 为空，让项目自动管理本地令牌。

### 5.2 最简单的外网方式：Cloudflare Tunnel

如果手机不能安装 Tailscale/WireGuard，可以使用项目内置的 Cloudflare Quick Tunnel。它只需要电脑安装一次 `cloudflared`，手机不需要安装 VPN，也不需要把 `8765` 端口转发到公网。

Windows 最短流程：

1. 双击 `install-cloudflared.cmd`，安装官方 `cloudflared`；安装完成后重新打开项目目录。
2. 双击 `start-monitor-cloudflare.vbs`，启动无黑色 CMD 窗口的电脑面板和 HTTPS 隧道。
3. 等待顶部按钮变为 `手机同步 ✓`，点击它，把“外网手机地址（HTTPS）”和 Token 填入手机 App。
4. 手机 App 的地址必须是 `https://...trycloudflare.com`，不要填写电脑局域网地址或训练服务器地址。

这个启动器会把 Cloudflare 隧道目标固定为电脑本机的 `127.0.0.1:8765`，并且会自动让本地同步中继只监听 `127.0.0.1`，因此不会再直接接受局域网网卡上的连接。手机仍然只读取电脑面板的只读快照。电脑面板关闭或网络断开后，手机同步会停止。

Quick Tunnel 生成的是临时地址，重启后可能变化，适合个人实验和快速查看；如果需要长期固定地址，再配置 Cloudflare 的命名 Tunnel 和自己的域名。无论哪种方式，都必须保留本地同步 Token，不要把 Token 提交到 GitHub 或发给他人。

安装命令行界面扩展：

```bash
python -m pip install -e ".[console]"
```

如果需要在本地重新处理导师像素素材，再安装像素资源工具：

```bash
python -m pip install -e ".[pixel]"
```

在服务器本机查看训练：

```bash
training-monitor console
```

从另一台电脑查看远程服务器：

```powershell
training-monitor console --url http://SERVER_IP:6006 --token YOUR_TOKEN
```

命令行界面会从服务器实时读取物理 GPU 探测结果，并按实际运行中的模型数量动态生成丹炉任务位：

- 导师像素小人是全局唯一的主炼丹师，无论服务器有几张 GPU 都只出现一次。
- 每个 `run_id` 对应一个模型丹炉；一个模型占用多张 GPU 时仍只显示一个丹炉。
- 物理 GPU 数量由服务器上的 `nvidia-smi` 自动探测，不使用固定卡数。
- 训练中显示温和微笑，验证/保存时切换动作；完成、停止或异常时切换为轻微严肃的状态。

快捷键：`Q` 退出，`R` 刷新，`1-9` 选择丹炉，`+/-` 调整历史曲线，`A` 切换纯 ASCII 模式。只查看一次可以使用：

```bash
training-monitor console --once --ascii
```

## 6. 安卓 App 使用

### 6.1 下载 APK

进入 Release 页面下载：

[https://github.com/Zephyer969/training-monitor/releases/latest](https://github.com/Zephyer969/training-monitor/releases/latest)

下载 `training-monitor.apk` 后安装到安卓手机。

如果手机提示不允许安装未知来源应用，需要在系统设置里允许当前浏览器或文件管理器安装应用。

如果你要在本地重新构建 APK，需要先安装 JDK 17 和 Android SDK，然后执行：

```bash
cd android
./gradlew :app:assembleDebug
```

Windows 可以执行：

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

### 6.2 填写连接信息

先在电脑上完成第 5.1 节，然后打开 App 的“设置”页填写：

- `本地面板地址`：桌面窗口“手机同步”弹窗提供的地址，例如 `http://192.168.1.20:8765`
- `本地同步 Token`：同一个弹窗提供的 Token；它和服务器端 `training-monitor connection` 的 Token 不同

填写后点击“保存并连接”。App 请求的是电脑的 `/api/status`，电脑再把当前桌面快照转给手机；手机不会直接连接训练服务器。

App 会显示：

- 总览：首页集中显示任务、状态、当前 epoch、进度、ETA、当前与最佳指标。
- 多 GPU 筛选：横向切换全部任务或单张 GPU。
- 训练趋势：按指标显示当前值、最佳值、最佳轮次和历史曲线。
- 显示指标：在设置中统一决定总览、趋势和通知显示哪些指标。
- 通知栏和锁屏训练状态，可显示 epoch、Best 指标和 ETA
- 训练完成提醒
- 手机端和电脑端统一使用深色蓝色像素风；移动端只展示信息，不显示导师、丹炉或 GPU 学徒动画。

指标名称在 App 中优先使用英文，例如 `Loss`、`Decode Loss`、`mIoU`、`mDice`、`mAP`、`Accuracy`，这样更接近训练面板和论文实验记录的习惯。

### 6.3 通知栏、锁屏和华为 FIT 4 手表同步

在 App 的 `设置` 页面开启 `通知栏训练状态`。

开启后：

- 手机通知栏会常驻显示训练状态。
- 锁屏界面可以看到当前 epoch、Best 指标和 ETA。
- 训练完成时会发送一次完成提醒。
- 通知里最多显示 1-2 个指标，来源是 `显示指标` 中勾选的前两个。

如果你使用华为 WATCH FIT 4，可以继续开启 `华为手表同步（FIT 4）`。App 会把训练状态通知优化成适合手表小屏显示的摘要，包含：

- 训练状态和进度百分比
- 当前 epoch / 总 epoch
- 当前主要指标
- Best 指标和对应 epoch
- ETA 预计剩余时间

FIT 4 通过华为运动健康同步手机通知显示训练状态，不需要在手表上单独安装 App。请在手机上确认：

- Android 系统通知权限已允许“炼丹台”。
- 华为运动健康中已允许“炼丹台”的通知同步到手表。
- FIT 4 的消息通知、勿扰模式和蓝牙连接状态正常。

如果手表没有显示，请先看手机通知栏是否有“炼丹台”的训练状态通知。手机端通知能正常显示后，再到华为运动健康里检查应用通知同步开关。

如果你希望在手表上随时打开一个独立页面查看训练状态，而不是只看通知，本仓库已经开始准备原生 FIT 4 companion：

```text
watch-fit4/
```

这个目录包含：

- 手机到手表的训练状态 JSON 协议。
- Android 手机侧 `WatchStatusPayload` 数据打包帮助类。
- FIT 4 Lite Wearable 页面骨架，可在 DevEco Studio 中继续接入 Wear Engine。

原生手表页面需要华为开发者账号、DevEco Studio、Wear Engine SDK、手表真机调试和签名配置；普通 Android APK 不能直接安装到 FIT 4 作为手表应用。

## 7. 离线缓存和历史数据

App 每次成功请求 `/api/status?history_limit=120` 后，都会把最近状态缓存在手机本地。为避免训练任务过多时拖慢启动，单次缓存超过 750 KB 会跳过写入，但当前页面仍会正常更新。

这意味着：

- 电脑端暂时无法连接训练服务器时，App 仍会显示电脑最后一次快照。
- 电脑或服务器关机后，App 仍能显示最后一次同步到手机的数据。
- 已经同步过的 loss / mIoU / mAP 曲线可以继续查看。

限制也很直接：如果训练完成后电脑从来没有同步到最终状态，电脑和服务器又已经关机，App 不可能凭空拿到未同步的数据。所以训练时建议保持电脑端面板持续运行。

服务器端也会把状态保存到安装目录：

```text
/root/autodl-tmp/training-monitor/state.json
```

如果后端服务暂时没启动，仍可尝试：

```bash
training-monitor status
```

新版命令会在服务不可用时读取本地缓存状态。

## 7. 自动检测训练

默认安装后会自动扫描训练日志。

默认扫描目录：

```text
/root/mmdetection*
/root/mmdetection3d*
/root/mmdet3d*
/root/mmsegmentation*
/root/mmclassification*
/root/mmpretrain*
/root/mmselfsup*
/root/mmyolo*
/root/mmpose*
/root/mmrotate*
/root/mmocr*
/root/mmaction*
/root/mmaction2*
/root/mmagic*
/root/mmediting*
/root/mmgeneration*
/root/mmtracking*
/root/mmtrack*
/root/mmrazor*
/root/mmhuman3d*
/root/mmfewshot*
/root/mmdeploy*
/root/work_dirs
/root/*/work_dirs
/root/autodl-tmp/*/work_dirs
/root/workspace/*/work_dirs
/root/autodl-tmp
/root/workspace
/root/runs
```

自动检测逻辑很简单：扫描这些目录里最新的支持文件，然后读取指标。

当前支持：

- OpenMMLab / MMEngine `.log`、`.json`、`.jsonl`：读取 `loss`、`mIoU`、`mDice`、`BBox mAP`、`Segm mAP`、`NDS`、`PQ`、`Top1 Acc`、`PCK`、`Hmean`、`MOTA`、`PSNR` 等常见指标
- `results.csv`：主要用于 YOLO / Ultralytics，读取 `mAP`
- 文件名包含 `result` / `metric` / `progress` 的 `.csv`

CSV 至少需要包含：

- `epoch`
- 一个指标列，例如 `mIoU`、`IoU`、`mAP`、`accuracy`、`acc`、`top1`

如果指标值是 `0.82` 这种 0 到 1 的小数，会自动转成 `82.0` 显示。

## 8. OpenMMLab 接入

大多数情况下不需要改训练代码。

只要你的 OpenMMLab 项目日志在默认扫描目录下，例如：

```text
/root/mmdetection/work_dirs/xxx/20260602_xxxxxx.log
/root/mmsegmentation-1.2.1/work_dirs/xxx/20260531_xxxxxx.log
/root/mmpose/work_dirs/xxx/vis_data/20260602_xxxxxx.json
```

安装服务后会自动识别最新日志。

如果日志目录不在默认位置：

```bash
training-monitor config set LOG_ROOTS "/你的/OpenMMLab/work_dirs"
training-monitor restart
```

如果想手动指定某一个日志文件：

```bash
training-monitor watch-file /path/to/train.log 300
```

最后的 `300` 是总 epoch，可以按你的训练轮数修改。

## 9. YOLO / Ultralytics 接入

YOLO 通常会生成：

```text
runs/detect/train/results.csv
runs/segment/train/results.csv
```

只要 `runs` 目录在扫描范围内，就会自动识别。

如果你的 YOLO 项目在 `/root/yolo-project`：

```bash
training-monitor config set LOG_ROOTS "/root/yolo-project/runs"
training-monitor restart
```

也可以手动指定：

```bash
training-monitor watch-file /root/yolo-project/runs/detect/train/results.csv 100
```

## 10. 通用 PyTorch 项目接入

如果你的项目不是 OpenMMLab 或 YOLO，推荐主动上报指标。

### 9.1 用 HTTP 接口上报

在训练代码里加：

```python
import requests

SERVER_URL = "http://你的服务器后端地址"
TOKEN = "你的 access token"

def report(epoch, total_epochs, value, metric_name="IoU", eta_seconds=None):
    payload = {
        "run_id": "my-experiment-001",
        "epoch": epoch,
        "total_epochs": total_epochs,
        "iou": float(value),
        "metric_name": metric_name,
        "status": "training",
    }
    if eta_seconds is not None:
        payload["eta_seconds"] = int(eta_seconds)

    requests.post(
        f"{SERVER_URL}/api/status",
        headers={"X-Monitor-Token": TOKEN},
        json=payload,
        timeout=3,
    ).raise_for_status()
```

自动日志 watcher 在首次同步历史数据时会使用 `POST /api/status/snapshot` 批量提交，避免逐条请求反复读写完整状态。自定义工具也可以发送 `{"updates": [ ... ]}`，单次最多 500 条；普通训练循环继续使用 `POST /api/status` 即可。

训练循环里调用：

```python
for epoch in range(1, total_epochs + 1):
    train_one_epoch()
    metric = validate()

    report(
        epoch=epoch,
        total_epochs=total_epochs,
        value=metric,
        metric_name="IoU",
    )
```

最后一轮可以把状态改成 `finished`：

```python
payload["status"] = "finished"
```

### 9.2 用项目自带 helper 上报

如果训练代码和监控服务在同一台服务器上，也可以直接使用项目里的 `TrainingMonitor`：

```python
import sys

sys.path.append("/root/autodl-tmp/training-monitor/server")

from training_monitor import TrainingMonitor

monitor = TrainingMonitor(
    "http://127.0.0.1:6006",
    token="你的 access token",
)

monitor.log(
    run_id="my-experiment-001",
    gpu_id="0",
    epoch=1,
    total_epochs=300,
    iou=76.5,
    metric_name="mIoU",
)
```

这里的参数含义：

- `run_id`：训练任务 ID。新任务建议换一个新的 ID。
- `gpu_id` / `gpu_ids`：可选。单卡训练传 `gpu_id="0"`；一个模型使用多卡训练传 `gpu_ids=["0", "1"]`。如果不传，helper 会尝试读取训练进程的 `CUDA_VISIBLE_DEVICES`。
- `epoch`：当前轮数。
- `total_epochs`：总轮数。
- `iou`：指标值。字段名为了兼容旧版本仍叫 `iou`，实际可以传 `mIoU`、`mAP`、`accuracy` 等指标。
- `metric_name`：App 上显示的指标名称。
- `eta_seconds`：预计剩余秒数，可选。
- `phase`：可选的细分阶段：`preparing`、`training`、`validating`、`saving`、`finished`、`stopped` 或 `error`，用于切换导师动作。
- `message`：可选的简短提示，会显示在当前丹炉和导师面板中。
- `status`：`training`、`paused`、`stopped`、`finished` 或 `error`。

命令行界面读取 `GET /api/status` 返回的 `hardware` 字段；也可以单独读取受 Token 保护的 `GET /api/hardware`。服务端通过本机 `nvidia-smi` 只读探测物理 GPU 数量和利用率，不把“当前运行过的 GPU ID”当成物理卡数量。

## 11. 新训练会不会自动切换

会。

后端会根据 `run_id` 判断是不是新的训练任务，并会同时保留多个正在训练的任务。自动检测模式下，`run_id` 默认就是日志文件路径。

多显卡场景下：

- 多个模型分别跑在不同显卡：每个训练任务使用不同 `run_id`，并上报对应 `gpu_id`。安卓端会出现 GPU 视图选择，可以切换查看对应任务。
- 一个模型使用多张显卡训练：保持同一个 `run_id`，上报 `gpu_ids=["0", "1"]` 这类列表。安卓端会把它当作一个训练任务展示，不需要额外选择显卡。

当检测到新的日志文件或新的 `results.csv` 后，会自动加入训练任务列表，并重新统计对应任务的最好指标。

如果自动检测选错了日志，通常是因为旧日志文件被重新写入，导致修改时间变成最新。解决办法是手动指定：

```bash
training-monitor watch-file /path/to/正确的日志文件 300
```

或者缩小扫描目录：

```bash
training-monitor config set LOG_ROOTS "/当前项目的训练输出目录"
training-monitor restart
```

## 12. 手机无法连接怎么办

先在电脑上确认桌面像素面板仍然打开，并点击 `手机同步` 查看地址和 Token：

```powershell
Get-Content .\monitor.local.token
```

手机填写的是电脑的 `本地面板地址`，不是服务器地址，也不是 `127.0.0.1`。

常见情况：

- 同一 Wi-Fi：确认手机和电脑在同一网段，并使用电脑的局域网 IPv4 地址。
- 人在外面：确认电脑和手机都在线于同一个 Tailscale/WireGuard 网络，并使用电脑的 VPN 地址。
- 手机不能安装 VPN：双击 `install-cloudflared.cmd` 后，再双击 `start-monitor-cloudflare.vbs`；等待“手机同步 ✓”，使用弹窗中的 HTTPS 地址。
- `HTTP 401`：说明本地同步 Token 填错，重新点击电脑端“手机同步”复制。
- `cloudflared 未找到`：重新打开项目目录；仍然找不到时，在 `monitor.config.json` 中填写 `cloudflared_path` 的完整路径，或把 `cloudflared.exe` 放在项目的 `tools` 目录。
- 外网地址打不开：确认电脑面板和 Cloudflare 隧道启动器都保持运行；Quick Tunnel 地址每次重启后可能变化。
- 连接超时：检查 Windows 防火墙是否允许 `8765/TCP` 专用网络入站访问，以及桌面端口是否被其他程序占用。
- 电脑端 SSH 断开：手机仍可能看到上一次快照，但不会产生新的训练数据；先恢复电脑端面板连接。

## 13. 安全建议

默认情况下，Training Monitor 只适合保存训练进度、loss、mIoU、mAP 这类实验指标，不要把数据集路径里的隐私信息或账号密码写进训练日志。

推荐做法：

- `access token` 只填在自己的手机 App 里，不要发到聊天、群、笔记或公开仓库。
- 如果 token 泄露，执行 `training-monitor rotate-token` 重新生成。
- 手机同步 Token 只用于电脑的只读接口；局域网或 Tailscale/WireGuard 私有地址可使用 HTTP，Cloudflare Tunnel 等公网方式必须使用 HTTPS。
- Cloudflare Tunnel 模式下，训练快照会经过 Cloudflare 隧道中转；不要把数据集隐私、账号密码或 SSH 凭据写进训练日志。
- GitHub 下载慢时可以手动使用镜像，但镜像源不是默认开启的。
- 如果自动扫描范围太大，用 `training-monitor config set LOG_ROOTS "/你的训练输出目录"` 缩小范围。

当前安全边界：

- 电脑端本地同步接口只开放 `GET /api/status` 和 `GET /api/health`，必须带 `X-Monitor-Token`；所有 POST 请求都会被拒绝。
- `/api/status`、`/api/status/snapshot` 和 `/api/reset` 必须带正确 `X-Monitor-Token`。
- API POST 请求体最大 4 MiB，且必须携带 `Content-Length`；连续错误 Token 尝试会被短时节流。
- API 响应默认使用 `Cache-Control: no-store`，避免训练状态或错误信息被中间缓存。
- token、配置文件、状态文件默认按当前用户私有权限保存。
- App 使用 Android Keystore 加密保存 token，并关闭系统备份。
- App 设置页提供“隐私与权限”说明，并支持清除训练缓存、清除本机 Token。
- 默认不启用浏览器跨域访问；如果你要做 Web 前端，再配置 `CORS_ORIGINS`。

## 14. 更新版本

在服务器上重新执行安装命令即可：

```bash
curl -fL https://github.com/Zephyer969/training-monitor/releases/latest/download/training-monitor-install-server.sh | bash
```

然后重启：

```bash
training-monitor restart
```

安卓 App 下载最新 Release 里的 APK 覆盖安装即可。

## 15. 卸载

先停止服务：

```bash
training-monitor stop
```

删除安装目录。

如果是默认 root + AutoDL 安装：

```bash
rm -rf /root/autodl-tmp/training-monitor
```

如果是普通用户安装：

```bash
rm -rf ~/.training-monitor
```

如果创建了命令软链接，也可以删除：

```bash
rm -f ~/.local/bin/training-monitor
rm -f ~/bin/training-monitor
```

## 16. 推荐使用方式

最省心的方式：

1. 在电脑端复制 `monitor.config.example.json` 为 `monitor.config.json`，只填写训练服务器 SSH 地址。
2. 双击 `start-monitor.vbs` 启动无黑色 CMD 窗口的像素面板。
3. 点击 `手机同步`，把电脑地址和本地同步 Token 填入手机 App。
4. OpenMMLab / YOLO 由电脑端自动检测；电脑端继续支持多卡、多模型和动态 GPU 布局。
5. 人在外面且手机不能安装 VPN 时，先运行 `install-cloudflared.cmd`，再双击 `start-monitor-cloudflare.vbs`，使用弹窗中的 HTTPS 地址；不要直接开放服务器 SSH 或监控端口。

这样换服务器时，只需修改电脑端 SSH 配置，手机仍然连接同一台电脑的本地面板地址，App 不需要重新配置服务器凭据。

## 17. 上架前清单

当前代码已经具备测试 APK、服务端安装脚本、Token 鉴权、App 本地加密保存 Token、首次使用隐私提示、通知权限说明、离线缓存和 OpenMMLab 常见日志自动识别能力。正式提交应用市场前，还需要补齐这些外部材料：

- 正式签名：在 GitHub Secrets 配置 `ANDROID_KEYSTORE_BASE64`、`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、`ANDROID_KEY_PASSWORD`，重新打包后得到正式 release APK。未配置这些密钥时，GitHub Release 会生成测试 APK，并同时上传 `training-monitor-build-info.txt` 标明 `market_ready=false`，不要用于应用市场提交。
- 隐私政策 URL：仓库已提供公开的 [`PRIVACY.md`](https://github.com/Zephyer969/training-monitor/blob/main/PRIVACY.md)，上架时仍需在应用市场和 GitHub Actions 变量中填写该 URL。
- App 备案：如果公开向中国大陆用户分发，按应用市场和接入服务商要求完成 APP 备案或相关主体信息提交。
- 主体资料：准备开发者姓名或主体名称、联系方式、应用名称“炼丹台”、作者“Zephyer”、包名 `com.modeltest.monitor`。
- 权限说明：首次使用时 App 会展示隐私与权限提示；说明只使用网络、通知、前台服务权限；不读取通讯录、定位、相册、麦克风、摄像头。
- 数据说明：说明本机保存本地面板地址、加密 Token、刷新间隔、勾选指标和最后一次训练状态缓存。
- 用户权利入口：App 设置页已提供清除训练缓存、清除本机 Token；如果后续增加账号体系，再补注销账号入口。
- 真机测试：至少在一台 Android 13+ 手机和一台 Android 12 或以下手机上测试安装、通知权限、锁屏通知、服务器连接、断网缓存。

参考依据：

- [《中华人民共和国个人信息保护法》](https://www.miit.gov.cn/zwgk/zcwj/flfg/art/2022/art_04a0f1fb5df244e39688fd5372623a8d.html)
- [《App违法违规收集使用个人信息行为认定方法》](https://wap.miit.gov.cn/jgsj/waj/wjfb/art/2020/art_8663d2afe61b40c3beb7c65bf6ec2a64.html)
- [《工业和信息化部关于开展移动互联网应用程序备案工作的通知》解读](https://www.miit.gov.cn/jgsj/xgj/hlwgl/art/2023/art_564bf0759d7e41d5b4aa8ce4996b9e84.html)

## 18. 隐私政策要点模板

正式上架前，把下面内容整理成一个可公开访问的网页，并把网页链接填写到应用市场后台。

- 应用名称：炼丹台
- 作者：Zephyer
- 包名：`com.modeltest.monitor`
- 功能用途：连接用户自行配置的本地电脑只读同步接口，展示模型训练进度、指标曲线、最佳指标、预计剩余时间和训练完成提醒。
- 收集的信息：本地面板地址、本地同步 Token、刷新间隔、用户勾选的显示指标、最后一次训练状态缓存。
- 使用目的：用于连接本地电脑面板、刷新训练状态、展示指标曲线、发送通知栏/锁屏训练状态提醒。
- 权限使用：网络权限用于访问本地电脑面板；通知权限和前台服务用于训练状态常驻通知和训练完成提醒。
- 不收集的信息：不读取通讯录、定位、相册、麦克风、摄像头，不采集身份证号、银行卡号、精确位置等敏感个人信息。
- 存储方式：Token 通过 Android Keystore 加密保存；训练状态缓存保存在本机；服务端 token、配置和状态文件默认按当前用户私有权限保存。
- 共享与第三方：当前 App 不接入广告 SDK，不向第三方共享个人信息。
- 删除方式：用户可在 App 设置页清除训练缓存、清除本机 Token；服务端可执行 `training-monitor rotate-token` 重新生成 token。
- 联系方式：上架前填写你的有效邮箱或其他联系方式。
