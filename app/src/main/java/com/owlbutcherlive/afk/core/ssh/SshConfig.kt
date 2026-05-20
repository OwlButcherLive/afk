package com.owlbutcherlive.afk.core.ssh

import com.owlbutcherlive.afk.domain.ConnectionConfig

/**
 * Configuration used by the SSH tunnel manager.
 */
data class SshConfig(
    val host: String,
    val port: Int,
    val username: String,
    val password: String?,
    val privateKeyPem: String?,
    val privateKeyPassphrase: String?,
    val remoteForwardPort: Int,
    val localForwardPort: Int,
    val timeoutSeconds: Int
) {
    companion object {
        fun fromConnectionConfig(config: ConnectionConfig): SshConfig = SshConfig(
            host = config.host,
            port = config.sshPort,
            username = config.username,
            password = config.password.takeIf { it.isNotBlank() },
            privateKeyPem = config.privateKeyPem.takeIf { it.isNotBlank() },
            privateKeyPassphrase = config.privateKeyPassphrase.takeIf { it.isNotBlank() },
            remoteForwardPort = config.remoteApiPort,
            localForwardPort = config.localForwardPort,
            timeoutSeconds = config.connectionTimeoutSeconds
        )
    }
}
