package com.owlbutcherlive.afk.feature.v2threads.data

import com.owlbutcherlive.afk.core.network.ApiClient
import com.owlbutcherlive.afk.core.network.V2GatewayApi
import com.owlbutcherlive.afk.core.network.V2Protocol
import com.owlbutcherlive.afk.core.network.V2ThreadListItem
import com.owlbutcherlive.afk.core.network.WebSocketClient
import com.owlbutcherlive.afk.core.network.V2Protocol.V2Event
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

class V2ThreadRepository(private val port: Int) {
    private val api: V2GatewayApi = ApiClient.createApi(V2GatewayApi::class.java)
    private val ws = WebSocketClient()

    private val _events = MutableStateFlow<V2Event?>(null)
    val events: StateFlow<V2Event?> = _events.asStateFlow()

    private val _threads = MutableStateFlow<List<V2ThreadListItem>>(emptyList())
    val threads: StateFlow<List<V2ThreadListItem>> = _threads.asStateFlow()

    suspend fun loadThreads(limit: Int = 50): Result<List<V2ThreadListItem>> {
        return try {
            val response = api.listThreads(limit)
            if (response.isSuccessful) {
                val items = response.body()?.threads ?: emptyList()
                _threads.value = items
                Result.success(items)
            } else {
                Result.failure(Exception("HTTP ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun connectWs(): Result<Unit> {
        return try {
            ws.connect(port, "/ws/v2/thread")
            collectWsEvents()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun collectWsEvents() {
        ws.messages.collect { raw ->
            val event = V2Protocol.parse(raw)
            if (event != null) {
                _events.value = event
            }
        }
    }

    fun sendHello() {
        ws.send(V2Protocol.hello())
    }

    fun subscribe(threadId: String) {
        ws.send(V2Protocol.subscribe(threadId))
    }

    fun startTurn(threadId: String, text: String) {
        ws.send(V2Protocol.startTurn(threadId, text))
    }

    fun requestSnapshot(threadId: String) {
        ws.send(V2Protocol.requestSnapshot(threadId))
    }

    fun disconnect() {
        ws.disconnect()
    }

    fun sendHeartbeat() {
        ws.send(V2Protocol.heartbeat())
    }
}
