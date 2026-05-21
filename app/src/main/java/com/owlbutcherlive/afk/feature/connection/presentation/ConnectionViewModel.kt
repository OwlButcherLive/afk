package com.owlbutcherlive.afk.feature.connection.presentation

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.owlbutcherlive.afk.core.common.ConnectionSession
import com.owlbutcherlive.afk.core.network.ApiClient
import com.owlbutcherlive.afk.core.network.WebSocketClient
import com.owlbutcherlive.afk.core.security.SecretStorage
import com.owlbutcherlive.afk.core.ssh.SshConfig
import com.owlbutcherlive.afk.core.ssh.SshConnectionResult
import com.owlbutcherlive.afk.domain.AuthMode
import com.owlbutcherlive.afk.domain.ConnectionConfig
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionEffect
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionIntent
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionUiState
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionStatus
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

class ConnectionViewModel(application: Application) : AndroidViewModel(application) {

    private val tunnelManager = ConnectionSession.tunnelManager
    private val secretStorage = SecretStorage(application)
    private val webSocketClient = WebSocketClient()

    private val _state = MutableStateFlow(ConnectionUiState())
    val state: StateFlow<ConnectionUiState> = _state.asStateFlow()

    private val _effects = Channel<ConnectionEffect>(Channel.CONFLATED)
    val effects = _effects.receiveAsFlow()

    init {
        processIntent(ConnectionIntent.LoadSavedCredentials)
    }

    fun processIntent(intent: ConnectionIntent) {
        when (intent) {
            is ConnectionIntent.UpdateHost -> setState { copy(host = intent.value) }
            is ConnectionIntent.UpdateSshPort -> setState { copy(sshPort = intent.value) }
            is ConnectionIntent.UpdateUsername -> setState { copy(username = intent.value) }
            is ConnectionIntent.UpdateAuthMode -> setState { copy(authMode = intent.mode) }
            is ConnectionIntent.UpdatePassword -> setState { copy(password = intent.value) }
            is ConnectionIntent.UpdatePrivateKey -> setState { copy(privateKeyPem = intent.value) }
            is ConnectionIntent.UpdatePrivateKeyPassphrase -> setState { copy(privateKeyPassphrase = intent.value) }
            is ConnectionIntent.UpdateRemoteApiPort -> setState { copy(remoteApiPort = intent.value) }
            is ConnectionIntent.UpdateLocalForwardPort -> setState { copy(localForwardPort = intent.value) }
            is ConnectionIntent.Connect -> connect()
            is ConnectionIntent.Disconnect -> disconnect()
            is ConnectionIntent.ClearError -> setState { copy(errorMessage = null, validationErrors = emptyList()) }
            is ConnectionIntent.LoadSavedCredentials -> loadSavedCredentials()
        }
    }

    private fun connect() {
        val config = buildConfig()
        if (!config.isValid()) {
            setState {
                copy(
                    connectionStatus = ConnectionStatus.Failed,
                    errorMessage = "Please fix the form errors below.",
                    validationErrors = config.validationErrors()
                )
            }
            return
        }

        setState {
            copy(
                connectionStatus = ConnectionStatus.Connecting,
                errorMessage = null,
                validationErrors = emptyList()
            )
        }

        saveCredentials(config)

        viewModelScope.launch {
            val sshConfig = SshConfig.fromConnectionConfig(config)
            val result = tunnelManager.connect(sshConfig)

            when (result) {
                is SshConnectionResult.Connected -> {
                    val port = result.localPort

                    // Configure networking layers to use the tunnel
                    ApiClient.configureForPort(port)

                    // Share the session state with other features
                    ConnectionSession.activate(
                        host = config.host,
                        sshPort = config.sshPort,
                        username = config.username,
                        tunnelPort = port,
                        remoteApiPort = config.remoteApiPort
                    )

                    setState {
                        copy(
                            connectionStatus = ConnectionStatus.Connected,
                            tunnelPort = port,
                            errorMessage = null
                        )
                    }
                    _effects.send(ConnectionEffect.NavigateToDashboard(config.host, config.remoteApiPort))
                }

                is SshConnectionResult.Failed -> {
                    setState {
                        copy(
                            connectionStatus = ConnectionStatus.Failed,
                            errorMessage = result.message,
                            tunnelPort = null
                        )
                    }
                    _effects.send(ConnectionEffect.ConnectionError(result.message))
                }

                is SshConnectionResult.Connecting -> {
                    // intermediate state, already handled
                }

                is SshConnectionResult.Disconnected -> {
                    setState {
                        copy(
                            connectionStatus = ConnectionStatus.Idle,
                            tunnelPort = null
                        )
                    }
                }
            }
        }
    }

    private fun disconnect() {
        setState { copy(connectionStatus = ConnectionStatus.Disconnecting) }
        viewModelScope.launch {
            webSocketClient.disconnect()
            ConnectionSession.deactivate()
            setState {
                copy(
                    connectionStatus = ConnectionStatus.Idle,
                    tunnelPort = null,
                    errorMessage = null
                )
            }
            _effects.send(ConnectionEffect.Disconnected)
        }
    }

    private fun buildConfig(): ConnectionConfig {
        val s = _state.value
        return ConnectionConfig(
            host = s.host.trim(),
            sshPort = s.sshPort.toIntOrNull() ?: 22,
            username = s.username.trim(),
            authMode = s.authMode,
            password = s.password,
            privateKeyPem = s.privateKeyPem,
            privateKeyPassphrase = s.privateKeyPassphrase,
            remoteApiPort = s.remoteApiPort.toIntOrNull() ?: 3344,
            localForwardPort = s.localForwardPort.toIntOrNull() ?: 3344
        )
    }

    private fun loadSavedCredentials() {
        val host = secretStorage.getHost()
        if (host == null) {
            setState { copy(isLoaded = true) }
            return
        }

        setState {
            copy(
                host = host,
                sshPort = secretStorage.getPort().toString(),
                username = secretStorage.getUsername() ?: "",
                authMode = AuthMode.valueOf(
                    secretStorage.getAuthMode() ?: AuthMode.PASSWORD.name
                ),
                password = secretStorage.getPassword() ?: "",
                privateKeyPem = secretStorage.getPrivateKey() ?: "",
                privateKeyPassphrase = secretStorage.getPrivateKeyPassphrase() ?: "",
                remoteApiPort = secretStorage.getRemoteApiPort().toString(),
                localForwardPort = secretStorage.getLocalForwardPort().toString(),
                isLoaded = true
            )
        }
    }

    private fun saveCredentials(config: ConnectionConfig) {
        secretStorage.saveHost(config.host)
        secretStorage.savePort(config.sshPort)
        secretStorage.saveUsername(config.username)
        secretStorage.saveAuthMode(config.authMode.name)
        secretStorage.saveRemoteApiPort(config.remoteApiPort)
        secretStorage.saveLocalForwardPort(config.localForwardPort)

        when (config.authMode) {
            AuthMode.PASSWORD -> {
                secretStorage.savePassword(config.password)
                secretStorage.savePrivateKey("")
                secretStorage.savePrivateKeyPassphrase("")
            }
            AuthMode.PRIVATE_KEY -> {
                secretStorage.savePrivateKey(config.privateKeyPem)
                secretStorage.savePrivateKeyPassphrase(config.privateKeyPassphrase)
                secretStorage.savePassword("")
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        tunnelManager.onDestroy()
        webSocketClient.disconnect()
    }

    private fun setState(update: ConnectionUiState.() -> ConnectionUiState) {
        _state.value = _state.value.update()
    }
}
