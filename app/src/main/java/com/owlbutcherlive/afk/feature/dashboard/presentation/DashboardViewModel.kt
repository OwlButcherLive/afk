package com.owlbutcherlive.afk.feature.dashboard.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.owlbutcherlive.afk.core.common.ConnectionSession
import com.owlbutcherlive.afk.core.network.ApiClient
import com.owlbutcherlive.afk.core.network.GatewayApi
import com.owlbutcherlive.afk.feature.dashboard.contract.DashboardEffect
import com.owlbutcherlive.afk.feature.dashboard.contract.DashboardIntent
import com.owlbutcherlive.afk.feature.dashboard.contract.DashboardUiState
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

class DashboardViewModel : ViewModel() {

    private val _state = MutableStateFlow(
        DashboardUiState(
            host = ConnectionSession.host,
            port = ConnectionSession.remoteApiPort,
            tunnelPort = ConnectionSession.tunnelPort,
            isConnected = ConnectionSession.isActive
        )
    )
    val state: StateFlow<DashboardUiState> = _state.asStateFlow()

    private val _effects = Channel<DashboardEffect>(Channel.CONFLATED)
    val effects = _effects.receiveAsFlow()

    init {
        if (ConnectionSession.isActive) {
            checkGatewayHealth()
        }
    }

    fun processIntent(intent: DashboardIntent) {
        when (intent) {
            DashboardIntent.CheckGatewayHealth -> checkGatewayHealth()
            DashboardIntent.Disconnect -> disconnect()
        }
    }

    private fun checkGatewayHealth() {
        setState { copy(gatewayStatus = DashboardUiState.GatewayStatus.Checking) }

        viewModelScope.launch {
            try {
                val api = ApiClient.createApi(GatewayApi::class.java)
                val response = api.healthCheck()
                if (response.isSuccessful) {
                    setState { copy(gatewayStatus = DashboardUiState.GatewayStatus.Reachable) }
                } else {
                    setState {
                        copy(
                            gatewayStatus = DashboardUiState.GatewayStatus.Unreachable,
                            errorMessage = "Gateway returned ${response.code()}"
                        )
                    }
                }
            } catch (e: Exception) {
                setState {
                    copy(
                        gatewayStatus = DashboardUiState.GatewayStatus.Unreachable,
                        errorMessage = "Gateway unreachable: ${e.message ?: "Unknown error"}"
                    )
                }
                _effects.send(DashboardEffect.GatewayError(e.message ?: "Unknown error"))
            }
        }
    }

    private fun disconnect() {
        viewModelScope.launch {
            ConnectionSession.deactivate()
            setState { copy(isConnected = false) }
            _effects.send(DashboardEffect.Disconnected)
        }
    }

    private fun setState(update: DashboardUiState.() -> DashboardUiState) {
        _state.value = _state.value.update()
    }
}
