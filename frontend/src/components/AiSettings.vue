<template>
  <div class="ai-settings">
    <!-- 提供商列表 -->
    <div class="page-card">
      <div class="card-header">
        <span class="card-title">模型提供商</span>
        <el-button type="primary" size="small" @click="showAddProvider">添加提供商</el-button>
      </div>

      <el-table :data="providers" stripe size="small">
        <el-table-column prop="name" label="提供商" width="120" />
        <el-table-column prop="base_url" label="API 地址" min-width="200" show-overflow-tooltip />
        <el-table-column label="模型数" width="80" align="center">
          <template #default="{ row }">{{ row.models?.length || 0 }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.id === 'ollama'" type="info" size="small">本地</el-tag>
            <el-tag v-else-if="row.is_configured" type="success" size="small">已配置</el-tag>
            <el-tag v-else type="warning" size="small">未配置</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <el-button size="small" @click="editProvider(row)">编辑</el-button>
            <el-button size="small" @click="testConnection(row)" :loading="testingId === row.id">测试</el-button>
            <el-button v-if="!row.is_builtin" size="small" type="danger" @click="deleteProvider(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 全局设置 -->
    <div class="page-card" style="margin-top: 16px">
      <div class="card-header">
        <span class="card-title">全局设置</span>
      </div>
      <el-form label-width="140px" style="max-width: 600px">
        <el-form-item label="温度参数">
          <el-slider v-model="globalConfig.temperature" :min="0" :max="1" :step="0.1" show-input :show-input-controls="false" />
        </el-form-item>
        <el-form-item label="最大输出 Token">
          <el-input-number v-model="globalConfig.max_tokens" :min="100" :max="8000" :step="100" />
        </el-form-item>

        <el-divider content-position="left">信号分析专用模型</el-divider>

        <el-form-item label="信号分析提供商">
          <el-select v-model="globalConfig.signal_analysis_provider" style="width: 100%" clearable placeholder="不指定则使用默认模型" @change="onProviderChange">
            <el-option label="（使用默认模型）" value="" />
            <el-option v-for="p in configuredProviders" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
          <div class="form-hint">{{ signalProviderHint }}</div>
        </el-form-item>
        <el-form-item label="信号分析模型">
          <el-select v-model="globalConfig.signal_analysis_model" style="width: 100%" clearable filterable allow-create placeholder="选择信号分析专用模型">
            <el-option label="（使用默认模型）" value="" />
            <el-option v-for="m in signalProviderModels" :key="m.value" :label="m.label" :value="m.value">
              <span>{{ m.label }}</span>
              <span v-if="m.desc" style="float: right; color: #8492a6; font-size: 11px">{{ m.desc }}</span>
            </el-option>
          </el-select>
          <div class="form-hint">{{ signalModelHint }}</div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="saveGlobalConfig" :loading="savingGlobal">保存设置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 编辑提供商对话框 -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑提供商' : '添加提供商'" width="600px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="提供商ID">
          <el-input v-model="editForm.id" :disabled="isEdit" placeholder="如: my-api" />
        </el-form-item>
        <el-form-item label="显示名称">
          <el-input v-model="editForm.name" placeholder="如: 我的API" />
        </el-form-item>
        <el-form-item label="API 地址">
          <el-input v-model="editForm.base_url" :disabled="editForm.id === 'ollama'" />
          <div v-if="editForm.id === 'ollama'" class="form-hint">
            Docker 环境自动使用 host.docker.internal 访问宿主机 Ollama
          </div>
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="editForm.api_key" type="password" show-password placeholder="可选" />
        </el-form-item>

        <el-divider content-position="left">模型列表</el-divider>

        <div style="margin-bottom: 8px">
          <el-button v-if="editForm.id === 'ollama'" size="small" @click="scanOllamaModels" :loading="scanning">
            扫描本地模型
          </el-button>
          <el-button size="small" @click="editForm.models.push({ value: '', label: '', desc: '' })">
            + 添加模型
          </el-button>
        </div>

        <div v-for="(m, idx) in editForm.models" :key="idx" style="display: flex; gap: 8px; margin-bottom: 8px">
          <el-input v-model="m.value" placeholder="模型ID" style="flex: 1" />
          <el-input v-model="m.label" placeholder="显示名称" style="flex: 1" />
          <el-input v-model="m.desc" placeholder="描述" style="flex: 1" />
          <el-button :icon="Delete" circle size="small" @click="editForm.models.splice(idx, 1)" />
        </div>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveProviderForm" :loading="savingProvider">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { aiApi } from '@/api/ai'
import { useAiStore } from '@/stores/ai'
import type { ProviderConfig, ModelInfo } from '@/api/ai'

const aiStore = useAiStore()
const providers = ref<ProviderConfig[]>([])
const dialogVisible = ref(false)
const isEdit = ref(false)
const testingId = ref('')
const scanning = ref(false)
const savingProvider = ref(false)
const savingGlobal = ref(false)

const globalConfig = reactive({
  temperature: 0.7,
  max_tokens: 2000,
  signal_analysis_provider: '',
  signal_analysis_model: '',
})

const editForm = reactive({
  id: '',
  name: '',
  base_url: '',
  api_key: '',
  models: [] as { value: string; label: string; desc: string }[],
})

// 只显示已配置的提供商（有 API Key 或是 Ollama）
const configuredProviders = computed(() => {
  return providers.value.filter(p => p.id === 'ollama' || p.is_configured)
})

// 当前默认提供商名称
const defaultProviderName = computed(() => {
  const p = configuredProviders.value.find(pr => pr.id === aiStore.lastProvider)
  return p?.name || configuredProviders.value[0]?.name || '未配置'
})

// 当前默认模型名称
const defaultModelName = computed(() => {
  return aiStore.lastModel || '未选择'
})

// 信号分析提供商提示
const signalProviderHint = computed(() => {
  if (globalConfig.signal_analysis_provider) return ''
  return `默认使用 ${defaultProviderName.value}`
})

// 信号分析模型提示
const signalModelHint = computed(() => {
  if (globalConfig.signal_analysis_model) return '可手动输入模型名称'
  return `默认使用 ${defaultModelName.value}`
})

// 信号分析提供商对应的模型列表
const signalProviderModels = computed(() => {
  const providerId = globalConfig.signal_analysis_provider
  if (!providerId) return []
  const provider = providers.value.find(p => p.id === providerId)
  return provider?.models || []
})

// 用户手动切换提供商时清空模型选择
function onProviderChange() {
  globalConfig.signal_analysis_model = ''
}

onMounted(async () => {
  await loadProviders()
  try {
    const config = await aiApi.getConfig()
    globalConfig.temperature = config.temperature
    globalConfig.max_tokens = config.max_tokens
    globalConfig.signal_analysis_provider = config.signal_analysis_provider || ''
    globalConfig.signal_analysis_model = config.signal_analysis_model || ''
  } catch {}
})

async function loadProviders() {
  try {
    providers.value = await aiApi.listProviders()
  } catch {
    providers.value = []
  }
}

function showAddProvider() {
  isEdit.value = false
  Object.assign(editForm, { id: '', name: '', base_url: '', api_key: '', models: [] })
  dialogVisible.value = true
}

function editProvider(provider: ProviderConfig) {
  isEdit.value = true
  Object.assign(editForm, {
    id: provider.id,
    name: provider.name,
    base_url: provider.base_url,
    api_key: provider.api_key,
    models: provider.models.map(m => ({ ...m })),
  })
  dialogVisible.value = true
}

async function saveProviderForm() {
  if (!editForm.id || !editForm.name || !editForm.base_url) {
    ElMessage.warning('请填写必要字段')
    return
  }
  savingProvider.value = true
  try {
    await aiApi.saveProvider({
      id: editForm.id,
      name: editForm.name,
      base_url: editForm.base_url,
      api_key: editForm.api_key,
      models: editForm.models.filter(m => m.value),
    })
    ElMessage.success('提供商已保存')
    dialogVisible.value = false
    await loadProviders()
    await aiStore.loadProviders()  // 同步到全局 store
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e?.message || '未知错误'))
  } finally {
    savingProvider.value = false
  }
}

async function deleteProvider(provider: ProviderConfig) {
  try {
    await ElMessageBox.confirm(`确定删除提供商 "${provider.name}"？`, '提示', { type: 'warning' })
    await aiApi.deleteProvider(provider.id)
    ElMessage.success('已删除')
    await loadProviders()
    await aiStore.loadProviders()  // 同步到全局 store
  } catch {}
}

async function scanOllamaModels() {
  scanning.value = true
  try {
    const models = await aiApi.listOllamaModels(editForm.base_url)
    editForm.models = models.map(m => ({
      value: m.name,
      label: m.name,
      desc: `${(m.size / 1e9).toFixed(1)}GB`,
    }))
    if (models.length === 0) {
      ElMessage.warning('未发现已安装的模型')
    } else {
      ElMessage.success(`发现 ${models.length} 个模型`)
    }
  } catch {
    ElMessage.error('无法连接 Ollama 服务')
  } finally {
    scanning.value = false
  }
}

async function testConnection(provider: ProviderConfig) {
  testingId.value = provider.id
  try {
    const res = await aiApi.testProvider(provider.id)
    if (res.connected) {
      ElMessage.success('连接正常')
    } else {
      ElMessage.error('连接失败: ' + (res.error || '请检查配置'))
    }
  } catch (e: any) {
    ElMessage.error('测试失败: ' + (e?.message || '未知错误'))
  } finally {
    testingId.value = ''
  }
}

async function saveGlobalConfig() {
  savingGlobal.value = true
  try {
    // 先读取当前完整配置，再合并更新
    const current = await aiApi.getConfig()
    await aiApi.updateConfig({
      ...current,
      temperature: globalConfig.temperature,
      max_tokens: globalConfig.max_tokens,
      signal_analysis_provider: globalConfig.signal_analysis_provider,
      signal_analysis_model: globalConfig.signal_analysis_model,
    })
    ElMessage.success('设置已保存')
  } catch {
    ElMessage.error('保存失败')
  } finally {
    savingGlobal.value = false
  }
}
</script>

<style lang="scss" scoped>
.ai-settings {
  .form-hint {
    font-size: 12px;
    color: #909399;
    margin-top: 4px;
  }
}
</style>
