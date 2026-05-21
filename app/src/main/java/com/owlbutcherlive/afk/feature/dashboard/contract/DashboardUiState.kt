package com.owlbutcherlive.afk.feature.dashboard.contract

/**
 * UI state for the post-connection dashboard screen.
 */
data class DashboardUiState(
    val host: String = "",
    val port: Int = 3344,
    val tunnelPort: Int = 0,
    val isConnected: Boolean = true,
    val gatewayStatus: GatewayStatus = GatewayStatus.Unknown,
    val errorMessage: String? = null
) {
    enum class GatewayStatus {
        Unknown,
        Checking,
        Reachable,
        Unreachable
    }
}
