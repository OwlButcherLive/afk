package com.owlbutcherlive.afk.feature.connection.contract

import com.owlbutcherlive.afk.domain.AuthMode

/**
 * Represents the complete UI state for the connection screen.
 */
data class ConnectionUiState(
    // Form fields
    val host: String = "",
    val sshPort: String = "22",
    val username: String = "",
    val authMode: AuthMode = AuthMode.PASSWORD,
    val password: String = "",
    val privateKeyPem: String = "",
    val privateKeyPassphrase: String = "",
    val remoteApiPort: String = "3344",
    val localForwardPort: String = "3344",

    // Connection lifecycle
    val connectionStatus: ConnectionStatus = ConnectionStatus.Idle,
    val tunnelPort: Int? = null,
    val errorMessage: String? = null,

    // Form validation
    val validationErrors: List<String> = emptyList(),

    // Saved credentials loaded flag
    val isLoaded: Boolean = false
)

/**
 * Connection lifecycle states.
 */
enum class ConnectionStatus {
    Idle,
    Connecting,
    Connected,
    Disconnecting,
    Failed
}
