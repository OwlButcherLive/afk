package com.owlbutcherlive.afk.feature.connection.contract

/**
 * One-shot side effects emitted by the ViewModel.
 */
sealed interface ConnectionEffect {
    data class TunnelReady(val port: Int) : ConnectionEffect
    data class NavigateToDashboard(
        val host: String,
        val port: Int
    ) : ConnectionEffect
    data class ConnectionError(val message: String) : ConnectionEffect
    data object Disconnected : ConnectionEffect
}
