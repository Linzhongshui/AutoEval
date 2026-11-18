# DeepSWE v1.1 数据部署

官方任务源为 https://github.com/datacurve-ai/deep-swe，固定提交 `0b9fabbb63b9104d678fe965e1632f2dd9eaa2ea`。服务器已校验并解包任务至 `~/autoeval-platform/datasets/deepswe-v1.1-0b9fabbb/tasks`。

在执行服务器运行：

```sh
sh install-deepswe-tasks.sh "$HOME/autoeval-platform/datasets/deepswe-v1.1-0b9fabbb/tasks" autoeval-automationbench-runner-shared
```

脚本核对任务目录，现有容器数据与来源目录不一致时退出。容器重建后可重新运行。控制台选择 `platform.deepswe-v11.v1.harbor`。全量 113 个任务，Lite 为 `abs-module-cache-flags`。

四数据集 Lite 环境预检 `42dbe2ea-5440-4eb1-8897-f068aa62dcdd` 中 GPQA 和 AutomationBench 通过。DeepSWE 剩余 `dataset_not_validated`。MMMU-Pro 仍需对齐工具身份并完成小样本验收。
