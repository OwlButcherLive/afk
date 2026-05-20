package com.owlbutcherlive.afk.domain

data class ConnectionConfig(
    val host: String,
    val sshPort: Int = 22,
    val username: String,
    val authMode: AuthMode = AuthMode.PASSWORD,
    val password: String = "",
    val privateKeyPem: String = "",
    val privateKeyPassphrase: String = "",
    val remoteApiPort: Int = 3344,
    val localForwardPort: Int = 3344,
    val connectionTimeoutSeconds: Int = 15
) {
    fun isValid(): Boolean {
        if (host.isBlank() || username.isBlank()) return false
        if (sshPort !in 1..65535) return false
        if (remoteApiPort !in 1..65535) return false
        if (localForwardPort !in 1..65535) return false
        return when (authMode) {
            AuthMode.PASSWORD -> password.isNotBlank()
            AuthMode.PRIVATE_KEY -> privateKeyPem.isNotBlank()
        }
    }

    fun validationErrors(): List<String> {
        val errors = mutableListOf<String>()
        if (host.isBlank()) errors.add("Host is required")
        if (username.isBlank()) errors.add("Username is required")
        if (sshPort !in 1..65535) errors.add("SSH port must be between 1 and 65535")
        if (remoteApiPort !in 1..65535) errors.add("Remote API port must be between 1 and 65535")
        if (localForwardPort !in 1..65535) errors.add("Local forward port must be between 1 and 65535")
        when (authMode) {
            AuthMode.PASSWORD -> if (password.isBlank()) errors.add("Password is required for password auth")
            AuthMode.PRIVATE_KEY -> if (privateKeyPem.isBlank()) errors.add("Private key is required for key auth")
        }
        return errors
    }
}
