package com.owlbutcherlive.afk.feature.dashboard.contract

sealed interface DashboardIntent {
    data object CheckGatewayHealth : DashboardIntent
    data object Disconnect : DashboardIntent
}
