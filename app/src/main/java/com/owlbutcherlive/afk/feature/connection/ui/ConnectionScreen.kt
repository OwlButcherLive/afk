package com.owlbutcherlive.afk.feature.connection.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.owlbutcherlive.afk.domain.AuthMode
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionEffect
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionIntent
import com.owlbutcherlive.afk.feature.connection.contract.ConnectionStatus
import com.owlbutcherlive.afk.feature.connection.presentation.ConnectionViewModel

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConnectionScreen(
    onConnected: () -> Unit = {},
    viewModel: ConnectionViewModel = viewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(Unit) {
        viewModel.effects.collect { effect ->
            when (effect) {
                is ConnectionEffect.NavigateToDashboard -> onConnected()
                else -> {}
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("AFK") },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            // Status banner
            ConnectionStatusBanner(
                status = state.connectionStatus,
                tunnelPort = state.tunnelPort,
                errorMessage = state.errorMessage,
                onDismissError = { viewModel.processIntent(ConnectionIntent.ClearError) }
            )

            // Validation errors
            if (state.validationErrors.isNotEmpty()) {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer
                    )
                ) {
                    Column(modifier = Modifier.padding(12.dp)) {
                        state.validationErrors.forEach { error ->
                            Text(
                                text = "• $error",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onErrorContainer
                            )
                        }
                    }
                }
            }

            // Connection form
            Text(
                text = "Server Connection",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary
            )

            OutlinedTextField(
                value = state.host,
                onValueChange = { viewModel.processIntent(ConnectionIntent.UpdateHost(it)) },
                label = { Text("Host") },
                placeholder = { Text("192.168.1.100 or debian.example.com") },
                leadingIcon = { Icon(Icons.Default.Dns, contentDescription = null) },
                singleLine = true,
                enabled = state.connectionStatus != ConnectionStatus.Connected,
                modifier = Modifier.fillMaxWidth()
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                OutlinedTextField(
                    value = state.sshPort,
                    onValueChange = { viewModel.processIntent(ConnectionIntent.UpdateSshPort(it)) },
                    label = { Text("SSH Port") },
                    leadingIcon = { Icon(Icons.Default.Tag, contentDescription = null) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.weight(1f)
                )

                OutlinedTextField(
                    value = state.remoteApiPort,
                    onValueChange = { viewModel.processIntent(ConnectionIntent.UpdateRemoteApiPort(it)) },
                    label = { Text("API Port") },
                    leadingIcon = { Icon(Icons.Default.Api, contentDescription = null) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.weight(1f)
                )
            }

            OutlinedTextField(
                value = state.username,
                onValueChange = { viewModel.processIntent(ConnectionIntent.UpdateUsername(it)) },
                label = { Text("Username") },
                leadingIcon = { Icon(Icons.Default.Person, contentDescription = null) },
                singleLine = true,
                enabled = state.connectionStatus != ConnectionStatus.Connected,
                modifier = Modifier.fillMaxWidth()
            )

            // Auth mode selector
            Text(
                text = "Authentication",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.primary
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                FilterChip(
                    selected = state.authMode == AuthMode.PASSWORD,
                    onClick = {
                        viewModel.processIntent(ConnectionIntent.UpdateAuthMode(AuthMode.PASSWORD))
                    },
                    label = { Text("Password") },
                    leadingIcon = {
                        Icon(
                            Icons.Default.Lock,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp)
                        )
                    },
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.weight(1f)
                )
                FilterChip(
                    selected = state.authMode == AuthMode.PRIVATE_KEY,
                    onClick = {
                        viewModel.processIntent(ConnectionIntent.UpdateAuthMode(AuthMode.PRIVATE_KEY))
                    },
                    label = { Text("Private Key") },
                    leadingIcon = {
                        Icon(
                            Icons.Default.VpnKey,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp)
                        )
                    },
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.weight(1f)
                )
            }

            if (state.authMode == AuthMode.PASSWORD) {
                var passwordVisible by remember { mutableStateOf(false) }

                OutlinedTextField(
                    value = state.password,
                    onValueChange = { viewModel.processIntent(ConnectionIntent.UpdatePassword(it)) },
                    label = { Text("Password") },
                    leadingIcon = { Icon(Icons.Default.Key, contentDescription = null) },
                    trailingIcon = {
                        IconButton(onClick = { passwordVisible = !passwordVisible }) {
                            Icon(
                                if (passwordVisible) Icons.Default.VisibilityOff
                                else Icons.Default.Visibility,
                                contentDescription = if (passwordVisible) "Hide password" else "Show password"
                            )
                        }
                    },
                    visualTransformation = if (passwordVisible) VisualTransformation.None
                    else PasswordVisualTransformation(),
                    singleLine = true,
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            if (state.authMode == AuthMode.PRIVATE_KEY) {
                OutlinedTextField(
                    value = state.privateKeyPem,
                    onValueChange = { viewModel.processIntent(ConnectionIntent.UpdatePrivateKey(it)) },
                    label = { Text("Private Key (PEM)") },
                    placeholder = { Text("-----BEGIN OPENSSH PRIVATE KEY-----\n...") },
                    leadingIcon = { Icon(Icons.Default.VpnKey, contentDescription = null) },
                    minLines = 4,
                    maxLines = 8,
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.fillMaxWidth()
                )

                var passphraseVisible by remember { mutableStateOf(false) }

                OutlinedTextField(
                    value = state.privateKeyPassphrase,
                    onValueChange = { viewModel.processIntent(ConnectionIntent.UpdatePrivateKeyPassphrase(it)) },
                    label = { Text("Passphrase (optional)") },
                    leadingIcon = { Icon(Icons.Default.Lock, contentDescription = null) },
                    trailingIcon = {
                        IconButton(onClick = { passphraseVisible = !passphraseVisible }) {
                            Icon(
                                if (passphraseVisible) Icons.Default.VisibilityOff
                                else Icons.Default.Visibility,
                                contentDescription = if (passphraseVisible) "Hide" else "Show"
                            )
                        }
                    },
                    visualTransformation = if (passphraseVisible) VisualTransformation.None
                    else PasswordVisualTransformation(),
                    singleLine = true,
                    enabled = state.connectionStatus != ConnectionStatus.Connected,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Connect / Disconnect button
            Button(
                onClick = {
                    when (state.connectionStatus) {
                        ConnectionStatus.Connected -> {
                            viewModel.processIntent(ConnectionIntent.Disconnect)
                        }
                        else -> {
                            viewModel.processIntent(ConnectionIntent.Connect)
                        }
                    }
                },
                enabled = state.connectionStatus != ConnectionStatus.Connecting &&
                        state.connectionStatus != ConnectionStatus.Disconnecting,
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (state.connectionStatus == ConnectionStatus.Connected)
                        MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary
                ),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
            ) {
                when (state.connectionStatus) {
                    ConnectionStatus.Idle -> {
                        Icon(Icons.Default.PlayArrow, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Connect")
                    }
                    ConnectionStatus.Connecting -> {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Connecting...")
                    }
                    ConnectionStatus.Connected -> {
                        Icon(Icons.Default.Stop, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Disconnect")
                    }
                    ConnectionStatus.Disconnecting -> {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.onError
                        )
                        Spacer(Modifier.width(8.dp))
                        Text("Disconnecting...")
                    }
                    ConnectionStatus.Failed -> {
                        Icon(Icons.Default.Refresh, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text("Retry")
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))
        }
    }
}

@Composable
private fun ConnectionStatusBanner(
    status: ConnectionStatus,
    tunnelPort: Int?,
    errorMessage: String?,
    onDismissError: () -> Unit
) {
    AnimatedVisibility(
        visible = status != ConnectionStatus.Idle,
        enter = fadeIn(),
        exit = fadeOut()
    ) {
        when (status) {
            ConnectionStatus.Connecting -> {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.tertiaryContainer
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp
                        )
                        Spacer(Modifier.width(12.dp))
                        Text(
                            text = "Establishing SSH tunnel...",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onTertiaryContainer
                        )
                    }
                }
            }

            ConnectionStatus.Connected -> {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Icon(
                            Icons.Default.CheckCircle,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary
                        )
                        Spacer(Modifier.width(12.dp))
                        Column {
                            Text(
                                text = "Tunnel Active",
                                style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer
                            )
                            Text(
                                text = "localhost:${tunnelPort ?: "?"} → remote API",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.8f)
                            )
                        }
                    }
                }
            }

            ConnectionStatus.Failed -> {
                errorMessage?.let { msg ->
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.errorContainer
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            modifier = Modifier.padding(16.dp),
                            verticalAlignment = Alignment.Top
                        ) {
                            Icon(
                                Icons.Default.Error,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.error
                            )
                            Spacer(Modifier.width(12.dp))
                            Text(
                                text = msg,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                modifier = Modifier.weight(1f)
                            )
                            IconButton(onClick = onDismissError) {
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "Dismiss",
                                    tint = MaterialTheme.colorScheme.onErrorContainer
                                )
                            }
                        }
                    }
                }
            }

            ConnectionStatus.Disconnecting -> {
                Card(
                    colors = CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.secondaryContainer
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Row(
                        modifier = Modifier.padding(16.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp
                        )
                        Spacer(Modifier.width(12.dp))
                        Text(
                            text = "Closing tunnel...",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSecondaryContainer
                        )
                    }
                }
            }

            ConnectionStatus.Idle -> { /* hidden */ }
        }
    }
}
