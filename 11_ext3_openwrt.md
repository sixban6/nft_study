# 扩展阶段三：OpenWrt 环境下的硬核生存指南

*类比 C 语言：在特定的 RTOS（实时操作系统）下做底层开发。*

在普通的 Linux 服务器（Ubuntu、Debian）上，我们可以随心所欲地控制 `nftables` 和 `iproute2`。但在 OpenWrt 这个为路由器量身定制的嵌入式系统中，玩法变了。
它有自己独特的一套生态系统来保证“网络接口随时热插拔”和“配置文件断电不丢失”。直接手写零散的底层命令不仅不优雅，还会在系统重启后立刻被清洗殆尽。

---

## 1. OpenWrt 的网络哲学：netifd 与 fw4

在 OpenWrt 22.03 版本及以上的现代世界里，两个守护神统治了网络：

**`netifd` (Network Interface Daemon)：**
由于路由器面临宽带重拨、网线拔插、WiFi 切换等复杂情况，传统的网络脚本无法满足动态需求。`netifd` 会以事件驱动（Event-Driven）的方式通过 C 语言级别的后台常驻守护进程来监控物理网卡。
当你通过网页（LuCI）修改接口时，底层是 `netifd` 调用了 `iproute2` 帮你创建和下发了路由表和 `ip rule`。

**`fw4` (Firewall4)：**
OpenWrt 最新的防火墙大厦基建。
**认清现实：底层已经完全由 `iptables` 切换到了 `nftables`。**
如果你去查阅 `/etc/config/firewall` 配置文件，你会发现它本质上只是 UCI（Unified Configuration Interface）系统的门面。每次你提交修改并点击“保存并应用”，`fw4` 就会读取 UCI，**将其一键自动编译成原生的 `nftables` 语言，并加载到内核中**。

这也意味着：不要想着用 `service firewall restart` 这类旧招去强塞 `iptables` 脚本了。

---

## 2. 绕过 GUI，注入原生代码

当 LuCI 形形色色的输入框满足不了你极尽变态的控制欲时（比如复杂的 `vmap` 字典控制或特定的 `meta mark`），你需要像外挂一样，优雅地给 `fw4` 注入纯手写的原生代码。

`fw4` 给高级黑客留了专属后门。默认行为中，`fw4` 在编译出最后那几千行规则集并推给 `nftables` 前，会加载 `/etc/nftables.d/` 目录和配置文件指定的自定义包含（Include）文件。

**如何正确地持久化自定义规则？**
你可以通过配置自定义规则的包含了注入手写代码：

1. 创建你的原生脚本，比如 `/etc/my_custom.nft`
2. 用传统的 `table inet fw4` 为底子。因为 `fw4` 把所有官方生成的链全部放在了 `inet fw4` 这张表里。
```bash
# 文件: /etc/my_custom.nft
# 我们的代码注入点
chain my_custom_blocker {
    # 只允许特定 IP 访问我们的硬核路由器后台
    ip saddr != 192.168.1.100 tcp dport 22 drop
    ip saddr != 192.168.1.100 tcp dport 80 drop
}
```
3. 在 `/etc/config/firewall` 中找到 include 段落并引入：
```text
config include
    option path '/etc/my_custom.nft'
    option type 'script'
    option fw4_compatible '1'
```
这样，每当路由器重启或者重载时，`fw4` 生成的主体表链中就会妥帖包含你写的原生 `nftables` 脚本，如同在官方内核代码中夹带私货一般，而且**绝不会被重写**。

---

## 3. OpenWrt 终极实战：局域网设备的分流与隔离

**需求挑战：** 
家里有一台电视机（必须直连不受干扰）、一部客人的手机（只能上外网，绝不允许看你内网的 NAS 内容）、还有一台你用来管理一切的主力电脑。

在传统的 OpenWrt 管理界面中处理“纯内网阻断”是非常笨拙的，但使用原生 `nftables` 就如同写了一段业务逻辑。

在我们的 `/etc/my_custom.nft` 中，我们将规则附加在负责内网转发的链中（在 fw4 中常为 `forward` 链或其细分的 `forward_lan` 链）：

```bash
# 在 inet fw4 的自定义链中进行分拣
chain lan_guest_isolation {
    
    # 电视机的 MAC 地址：11:22:33:44:55:66 
    # 客人手机的 IP 段：192.168.1.200-192.168.1.250
    # 内网 NAS 网段：192.168.1.10
    
    # 隔离访客：源 IP 为客人，目的 IP 为你的 NAS，无情丢弃！(局域网内且跨网段，或隔离)
    # 注意：如果客人在同网段且靠二层交换机直连，防火墙管不到，必须隔离 AP。这里假定跨网桥或三层隔离状态。
    ip saddr 192.168.1.200-192.168.1.250 ip daddr 192.168.1.10 drop
    
    # 电视机免除一切处理，直接 accept 返还给内核发出去
    ether saddr 11:22:33:44:55:66 accept
    
    # 其他流量默认放行
    accept
}
```
然后你需要把调用这个 `lan_guest_isolation` 的函数插到 `fw4` 的主 `forward` 钩子链中（如果不想依赖具体的 `fw4` 细分链，可以在文件开头自定义一个高优先级的钩子直接抢断）。

通过这种底层嵌入式的代码注入，你可以直接将最高效的 `ether saddr`（MAC匹配）、IP段匹配注入 OpenWrt。

到这里，你不仅掌握了网络层逻辑，还拥有了路由指针的管理甚至熟练在 RTOS 级环境里做定制固件底包开发，真正的《网络黑魔法防御术》已经结业毕业！
