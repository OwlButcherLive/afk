package com.owlbutcherlive.afk.core.ssh

import com.owlbutcherlive.afk.domain.ConnectionConfig

/**
 * Represents the result of an SSH tunnel operation.
 */
sealed interface SshConnectionResult {
    data object Connecting : SshConnectionResult
    data class Connected(val localPort: Int) : SshConnectionResult
    data class Failed(val message: String, val throwable: Throwable? = null) : SshConnectionResult
    data object Disconnected : SshConnectionResult
}
