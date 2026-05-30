# APTV 央视频直播源

自用 APTV 央视/CGTN 直播源维护目录。

## 文件

- `yangshipin.m3u`：APTV 可直接导入的 M3U 直播源。
- `sports.m3u`：自用看球精简源，只保留 CCTV5、CCTV5+、CCTV16、风云足球等频道。
- `sources.json`：上游公开源列表和频道筛选规则。
- `update_yangshipin.py`：拉取上游、筛选央视/CGTN、去重并重写 `yangshipin.m3u`。
- `sports_sources.json`：看球源的上游和目标频道配置。
- `update_sports.py`：拉取候选源、探活、排序并重写 `sports.m3u`。
- `sports_update_report.txt`：最近一次看球源更新报告。

## 更新

```bash
python3 update_yangshipin.py
python3 update_sports.py
```

## APTV 使用

看球源公网地址：

```text
https://ueh231.github.io/aptv-sports-source/sports.m3u
```

在 APTV 里添加上面这个订阅地址即可。

如果要发布到公网，先登录 GitHub CLI：

```bash
gh auth login
```

然后运行：

```bash
./publish_to_github_pages.sh
```

发布后 APTV 使用脚本输出的 `https://.../sports.m3u` 地址。

建议节目单使用：

```text
https://epg.aptv.app/xml
```

## 说明

直播源来自互联网公开资源，文件只保存索引，不存储任何视频内容。部分频道可能受网络、IPv6、运营商或版权限制影响。
