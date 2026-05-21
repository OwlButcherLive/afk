package com.owlbutcherlive.afk.feature.v2threads.presentation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.owlbutcherlive.afk.core.common.ConnectionSession
import com.owlbutcherlive.afk.core.network.V2Protocol.V2Event
import com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsEffect
import com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsIntent
import com.owlbutcherlive.afk.feature.v2threads.contract.V2ThreadsUiState
import com.owlbutcherlive.afk.feature.v2threads.data.V2ThreadRepository
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

class V2ThreadsViewModel : ViewModel() {
    private val port = ConnectionSession.remoteApiPort
    private val repository = V2ThreadRepository(port)

    private val _state = MutableStateFlow(V2ThreadsUiState())
    val state: StateFlow<V2ThreadsUiState> = _state.asStateFlow()

    private val _effects = Channel<V2ThreadsEffect>(Channel.BUFFERED)
    val effects = _effects.receiveAsFlow()

    init {
        viewModelScope.launch {
            repository.events.collect { event ->
                if (event != null) {
                    handleEvent(event)
                }
            }
        }
        viewModelScope.launch {
            repository.threads.collect { threads ->
                _state.value = _state.value.copy(threads = threads)
            }
        }
    }

    fun onIntent(intent: V2ThreadsIntent) {
        when (intent) {
            is V2ThreadsIntent.LoadThreads -> loadThreads()
            is V2ThreadsIntent.OpenThread -> openThread(intent.threadId, intent.title)
            is V2ThreadsIntent.SendMessage -> sendMessage(intent.text)
            is V2ThreadsIntent.ConnectWs -> connectWs()
            is V2ThreadsIntent.Disconnect -> disconnect()
            is V2ThreadsIntent.ToggleDebug -> toggleDebug()
            is V2ThreadsIntent.Refresh -> loadThreads()
        }
    }

    private fun loadThreads() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoading = true, statusMessage = "Loading threads...")
            val result = repository.loadThreads()
            result.fold(
                onSuccess = { items ->
                    _state.value = _state.value.copy(
                        isLoading = false,
                        statusMessage = "${items.size} thread(s) loaded",
                    )
                },
                onFailure = { e ->
                    _state.value = _state.value.copy(
                        isLoading = false,
                        statusMessage = "Error: ${e.message}",
                    )
                    _effects.send(V2ThreadsEffect.ShowError("Failed to load threads: ${e.message}"))
                },
            )
        }
    }

    private fun openThread(threadId: String, title: String) {
        _state.value = _state.value.copy(
            selectedThreadId = threadId,
            selectedThreadTitle = title,
            messages = emptyList(),
            statusMessage = "Opening: $title",
        )
        repository.subscribe(threadId)
        repository.requestSnapshot(threadId)
    }

    private fun sendMessage(text: String) {
        val threadId = _state.value.selectedThreadId ?: return
        if (text.isBlank()) return
        repository.startTurn(threadId, text.trim())
        _state.value = _state.value.copy(inputText = "")
    }

    private fun connectWs() {
        viewModelScope.launch {
            _state.value = _state.value.copy(statusMessage = "Connecting WS...")
            val result = repository.connectWs()
            result.fold(
                onSuccess = {
                    repository.sendHello()
                    repository.subscribeHealth()
                    _state.value = _state.value.copy(
                        wsConnected = true,
                        statusMessage = "WS connected",
                    )
                },
                onFailure = { e ->
                    _state.value = _state.value.copy(
                        statusMessage = "WS failed: ${e.message}",
                    )
                    _effects.send(V2ThreadsEffect.ShowError("WS connection failed: ${e.message}"))
                },
            )
        }
    }

    private fun disconnect() {
        repository.disconnect()
        _state.value = _state.value.copy(
            wsConnected = false,
            selectedThreadId = null,
            messages = emptyList(),
            statusMessage = "Disconnected",
        )
    }

    private fun toggleDebug() {
        _state.value = _state.value.copy(showDebug = !_state.value.showDebug)
    }

    private suspend fun handleEvent(event: V2Event) {
        _state.value = _state.value.copy(
            lastEvent = event,
            lastEventType = event::class.simpleName ?: "Unknown",
        )

        when (event) {
            is V2Event.ThreadSnapshot -> {
                val items = event.items
                _state.value = _state.value.copy(
                    messages = items,
                    statusMessage = "Snapshot: ${items.size} items",
                )
            }
            is V2Event.ItemAppended -> {
                val updated = _state.value.messages + event.item
                _state.value = _state.value.copy(messages = updated)
            }
            is V2Event.TurnStarted -> {
                _state.value = _state.value.copy(
                    statusMessage = "Turn started: ${event.turnId}",
                )
            }
            is V2Event.TurnCompleted -> {
                _state.value = _state.value.copy(
                    statusMessage = "Turn completed (${event.durationMs}ms)",
                )
            }
            is V2Event.TurnFailed -> {
                _state.value = _state.value.copy(
                    statusMessage = "Turn failed: ${event.error}",
                )
            }
            is V2Event.HelloResponse -> {
                _state.value = _state.value.copy(
                    statusMessage = "V2 protocol ${event.protocolVersion}, ${event.runtimes.size} runtime(s)",
                )
            }
            is V2Event.Ack -> {
                _state.value = _state.value.copy(
                    statusMessage = "Ack: ${event.status}",
                )
            }
            is V2Event.Error -> {
                _state.value = _state.value.copy(
                    statusMessage = "Error: ${event.message}",
                )
                _effects.send(V2ThreadsEffect.ShowError("${event.code}: ${event.message}"))
            }
            is V2Event.Pong -> {
                _state.value = _state.value.copy(statusMessage = "Heartbeat OK")
            }
            is V2Event.ItemUpdated -> {
                // Replace item in the messages list by id
                val updated = _state.value.messages.map { msg ->
                    if (msg.id == event.item.id) event.item else msg
                }
                _state.value = _state.value.copy(
                    messages = updated,
                    statusMessage = "Item updated: ${event.item.id}",
                )
            }
            is V2Event.ConnectionHealthChanged -> {
                _state.value = _state.value.copy(
                    healthState = event.newState,
                    healthDisconnects = event.disconnectedCount,
                    statusMessage = "Health: ${event.oldState} → ${event.newState}",
                )
            }
            else -> {}
        }
    }

    override fun onCleared() {
        super.onCleared()
        repository.disconnect()
    }
}
