package com.owlbutcherlive.afk.feature.v2threads.contract

import com.owlbutcherlive.afk.core.network.V2Protocol
import com.owlbutcherlive.afk.core.network.V2ThreadListItem

data class V2ThreadsUiState(
    val threads: List<V2ThreadListItem> = emptyList(),
    val selectedThreadId: String? = null,
    val selectedThreadTitle: String = "",
    val lastEvent: V2Protocol.V2Event? = null,
    val lastEventType: String = "",
    val messages: List<V2Protocol.V2Item> = emptyList(),
    val statusMessage: String = "Ready",
    val isLoading: Boolean = false,
    val wsConnected: Boolean = false,
    val showDebug: Boolean = true,
    val inputText: String = "",
)
