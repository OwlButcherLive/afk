package com.owlbutcherlive.afk.feature.sessions.contract

import com.owlbutcherlive.afk.domain.ChatSession

data class SessionsUiState(
    val sessions: List<ChatSession> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null,
    val isCreating: Boolean = false,
    val showAgentPicker: Boolean = false,
    val agents: List<com.owlbutcherlive.afk.domain.ChatAgent> = emptyList(),
    val agentsLoading: Boolean = false
)
