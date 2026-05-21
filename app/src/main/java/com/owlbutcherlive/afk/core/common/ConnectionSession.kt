package com.owlbutcherlive.afk.core.common

import com.owlbutcherlive.afk.core.network.ApiClient
import com.owlbutcherlive.afk.core.ssh.TunnelManager
import kotlinx.coroutines.GlobalScope
import kotlinx.coroutines.launch

/**
 * Singleton holding the active SSH session state.
 * Written by ConnectionViewModel on successful connect,
 * read by DashboardViewModel and other features.
 *
 * V1 pragmatic approach — avoids DI framework overhead.
 */
object ConnectionSession {
    var host: String = ""
    var sshPort: Int = 22
    var username: String = ""
    var tunnelPort: Int = 0
    var remoteApiPort: Int = 3344
    var isActive: Boolean = false
        private set
    val tunnelManager = TunnelManager()

    fun activate(
        host: String,
        sshPort: Int,
        username: String,
        tunnelPort: Int,
        remoteApiPort: Int
    ) {
        this.host = host
        this.sshPort = sshPort
        this.username = username
        this.tunnelPort = tunnelPort
        this.remoteApiPort = remoteApiPort
        this.isActive = true
    }

    fun deactivate() {
        GlobalScope.launch {
            tunnelManager.disconnect()
        }
        ApiClient.reset()
        isActive = false
        host = ""
        sshPort = 22
        username = ""
        tunnelPort = 0
        remoteApiPort = 3344
    }
}
