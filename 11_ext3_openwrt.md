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

## 3. OpenWrt 终极实战：基于 Docker 的底层注入演练

**需求挑战：** 
家里有一台电视机（必须绑定特权 MAC 不受干扰）、一部客人的手机（被分配到了 `192.168.1.200`，只允许上外网，绝不允许看内网 `nas_net` 下的内容），还有一台深藏功与名的 NAS。

在传统的 OpenWrt 管理界面中处理“纯内网阻断”是非常笨拙的，但使用原生 `nftables` 就如同写了一段业务逻辑。为了验证代码流，我们直接在 Docker 跑起一个包含 router, tv, guest, nas 四个容器的模拟局域网：

### 步骤 0：启动实验拓扑

创建一个 `docker-compose.yml`，我们给 TV 分配了一个独一无二的 MAC 地址 `00:11:22:33:44:55`：
```yaml
services:
  router:
    image: alpine:latest
    container_name: openwrt_sim_router
    cap_add: [NET_ADMIN]
    sysctls: [net.ipv4.ip_forward=1]
    command: sh -c "apk add --no-cache nftables && tail -f /dev/null"
    networks:
      lan: { ipv4_address: 192.168.1.254 }
      nas_net: { ipv4_address: 192.168.2.254 }

  tv:
    image: alpine:latest
    container_name: openwrt_sim_tv
    mac_address: 00:11:22:33:44:55
    cap_add: [NET_ADMIN]
    command: sh -c "apk add --no-cache iproute2 iputils && ip route del default || true && ip route add default via 192.168.1.254 && tail -f /dev/null"
    networks:
      lan: { ipv4_address: 192.168.1.11 }
    depends_on: [router]

  guest:
    image: alpine:latest
    container_name: openwrt_sim_guest
    cap_add: [NET_ADMIN]
    command: sh -c "apk add --no-cache iproute2 iputils && ip route del default || true && ip route add default via 192.168.1.254 && tail -f /dev/null"
    networks:
      lan: { ipv4_address: 192.168.1.200 }
    depends_on: [router]

  nas:
    image: alpine:latest
    container_name: openwrt_sim_nas
    cap_add: [NET_ADMIN]
    command: sh -c "apk add --no-cache iproute2 iputils && ip route del default || true && ip route add default via 192.168.2.254 && tail -f /dev/null"
    networks:
      nas_net: { ipv4_address: 192.168.2.10 }
    depends_on: [router]

networks:
  lan:
    ipam: { config: [{ subnet: 192.168.1.0/24 }] }
  nas_net:
    ipam: { config: [{ subnet: 192.168.2.0/24 }] }
```
终端执行 `docker compose up -d` 启动环境。稍等数秒，待路由器的 `nftables` 安装完毕，并手工模拟 OpenWrt 祖传的 `fw4` 底层大表：
```bash
docker exec openwrt_sim_router nft add table inet fw4
docker exec openwrt_sim_router nft 'add chain inet fw4 forward { type filter hook forward priority 0 ; policy accept ; }'
```

### 步骤 1：编写原生过滤脚本并注入

在你的主机随意创建一个 `/etc/my_custom.nft` 或者当前目录下的 `my_custom.nft` 脚本：
```bash
#!/usr/sbin/nft -f
# 文件: my_custom.nft
table inet fw4 {
    chain lan_guest_isolation {
        # 隔离访客：源 IP 为客人区，目标为 NAS，无情丢弃！
        ip saddr 192.168.1.200-192.168.1.250 ip daddr 192.168.2.10 drop
        
        # 电视机免除一切处理，直接 accept
        ether saddr 00:11:22:33:44:55 accept
    }
}
```
把规则推给路由器并执行：
```bash
docker cp my_custom.nft openwrt_sim_router:/etc/my_custom.nft
docker exec openwrt_sim_router nft -f /etc/my_custom.nft
```

然后，你需要把调用这个 `lan_guest_isolation` 的函数跳转挂载到 `fw4` 的主 `forward` 钩子链中：
```bash
docker exec openwrt_sim_router nft 'add rule inet fw4 forward jump lan_guest_isolation'
```

### 终极验证：冷酷的包过滤

通过这种底层嵌入式的代码注入，你可以直接将最高效的 `ether saddr`（MAC匹配）、IP段匹配注入 OpenWrt 过滤栈中。我们来测试结果：

1. **测试防贼防盗的客房设备：**
```bash
docker exec openwrt_sim_guest ping -c 1 -W 2 192.168.2.10
# 结果：100% packet loss (因为命中 ip saddr drop，直接陨灭)
```

2. **测试尊贵的 MAC 级特权设备 (TV)：**
```bash
docker exec openwrt_sim_tv ping -c 1 -W 2 192.168.2.10
# 结果：1 packets transmitted, 1 received, 0% packet loss (顺利通行！)
```

到这里，你不仅掌握了网络层核心逻辑，还具备了在 RTOS 级环境里做定制固件底包开发甚至黑客级 hook 注入的能力，真正的《网络黑魔法防御术》已经正式毕业结课！
