package com.owlbutcherlive.afk.feature.dashboard.contract

sealed interface DashboardEffect {
    data object Disconnected : DashboardEffect
    data class GatewayError(val message: String) : DashboardEffect
}
