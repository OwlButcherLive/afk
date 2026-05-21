package com.owlbutcherlive.afk.feature.sessions.presentation

import android.app.Application
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.owlbutcherlive.afk.core.network.ApiClient
import com.owlbutcherlive.afk.core.network.ChatApi
import com.owlbutcherlive.afk.domain.AgentOnlineStatus
import com.owlbutcherlive.afk.domain.ChatAgent
import com.owlbutcherlive.afk.domain.ChatSession
import com.owlbutcherlive.afk.feature.sessions.contract.SessionsEffect
import com.owlbutcherlive.afk.feature.sessions.contract.SessionsIntent
import com.owlbutcherlive.afk.feature.sessions.contract.SessionsUiState
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

class SessionsViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "SessionsViewModel"
    }

    private val chatApi: ChatApi = ApiClient.createApi(ChatApi::class.java)

    private val _state = MutableStateFlow(SessionsUiState())
    val state: StateFlow<SessionsUiState> = _state.asStateFlow()

    private val _effects = Channel<SessionsEffect>(Channel.CONFLATED)
    val effects = _effects.receiveAsFlow()

    init {
        loadSessions()
    }

    fun processIntent(intent: SessionsIntent) {
        when (intent) {
            SessionsIntent.LoadSessions -> loadSessions()
            SessionsIntent.CreateNewSession -> showAgentPicker()
            is SessionsIntent.SelectAgent -> createSession(intent.agentId)
            SessionsIntent.DismissAgentPicker -> setState { copy(showAgentPicker = false) }
            SessionsIntent.RetryLoad -> loadSessions()
        }
    }

    private fun loadSessions() {
        setState { copy(isLoading = true, error = null) }
        viewModelScope.launch {
            try {
                val response = chatApi.getSessions()
                if (response.isSuccessful) {
                    val sessions = response.body()?.sessions?.map { dto ->
                        ChatSession(
                            id = dto.id,
                            agentId = dto.agentId,
                            title = dto.title,
                            lastMessagePreview = dto.lastMessagePreview,
                            updatedAt = dto.updatedAt
                        )
                    } ?: emptyList()
                    setState { copy(sessions = sessions, isLoading = false) }
                } else {
                    setState {
                        copy(
                            isLoading = false,
                            error = "Failed to load sessions (${response.code()})"
                        )
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to load sessions: ${e.message}", e)
                setState {
                    copy(
                        isLoading = false,
                        error = "Could not load sessions: ${e.message ?: "Unknown error"}"
                    )
                }
            }
        }
    }

    private fun showAgentPicker() {
        setState { copy(showAgentPicker = true, agentsLoading = true, agents = emptyList()) }
        viewModelScope.launch {
            try {
                val response = chatApi.getAgents()
                if (response.isSuccessful) {
                    val agents = response.body()?.agents?.map { dto ->
                        ChatAgent(
                            id = dto.id,
                            name = dto.name,
                            status = AgentOnlineStatus.fromApi(dto.status)
                        )
                    } ?: emptyList()
                    setState { copy(agents = agents, agentsLoading = false) }
                } else {
                    setState { copy(agentsLoading = false) }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to load agents: ${e.message}", e)
                setState { copy(agentsLoading = false) }
            }
        }
    }

    private fun createSession(agentId: String) {
        setState { copy(isCreating = true, showAgentPicker = false) }
        viewModelScope.launch {
            try {
                val response = chatApi.createSession(
                    com.owlbutcherlive.afk.core.network.CreateSessionRequest(agentId = agentId)
                )
                if (response.isSuccessful) {
                    val session = response.body()!!
                    _effects.send(
                        SessionsEffect.NavigateToSession(
                            sessionId = session.id,
                            sessionTitle = session.title,
                            agentId = session.agentId
                        )
                    )
                } else {
                    setState {
                        copy(
                            isCreating = false,
                            error = "Failed to create session (${response.code()})"
                        )
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Failed to create session: ${e.message}", e)
                setState {
                    copy(
                        isCreating = false,
                        error = "Could not create session: ${e.message ?: "Unknown error"}"
                    )
                }
            }
        }
    }

    private fun setState(update: SessionsUiState.() -> SessionsUiState) {
        _state.value = _state.value.update()
    }
}
