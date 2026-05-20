package com.owlbutcherlive.afk.feature.connection.contract

import com.owlbutcherlive.afk.domain.AuthMode

/**
 * User actions that flow through the ViewModel.
 */
sealed interface ConnectionIntent {
    data class UpdateHost(val value: String) : ConnectionIntent
    data class UpdateSshPort(val value: String) : ConnectionIntent
    data class UpdateUsername(val value: String) : ConnectionIntent
    data class UpdateAuthMode(val mode: AuthMode) : ConnectionIntent
    data class UpdatePassword(val value: String) : ConnectionIntent
    data class UpdatePrivateKey(val value: String) : ConnectionIntent
    data class UpdatePrivateKeyPassphrase(val value: String) : ConnectionIntent
    data class UpdateRemoteApiPort(val value: String) : ConnectionIntent
    data class UpdateLocalForwardPort(val value: String) : ConnectionIntent
    data object Connect : ConnectionIntent
    data object Disconnect : ConnectionIntent
    data object ClearError : ConnectionIntent
    data object LoadSavedCredentials : ConnectionIntent
}
