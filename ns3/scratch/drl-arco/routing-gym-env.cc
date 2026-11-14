/* SPDX-License-Identifier: GPL-2.0-only */
// ns-3's scratch CMake picks the entry-point source by a plain text search for the name of
// the C++ entry function followed by a parenthesis. Keep that text out of this file, even
// in comments or in identifiers that end with those letters. tests/test_config_sync.py checks.
#include "routing-gym-env.h"

#include <algorithm>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("RoutingGymEnv");
NS_OBJECT_ENSURE_REGISTERED(RoutingGymEnv);

TypeId
RoutingGymEnv::GetTypeId()
{
    static TypeId tid =
        TypeId("ns3::RoutingGymEnv").SetParent<OpenGymEnv>().SetGroupName("OpenGym");
    return tid;
}

RoutingGymEnv::RoutingGymEnv(Time stepTime,
                             NodeContainer nodes,
                             std::vector<DirectedLink> links,
                             std::vector<Ipv4Address> nodeAddress,
                             std::vector<Ptr<OnOffApplication>> apps,
                             std::vector<double> flowRates,
                             Ptr<FlowMonitor> monitor,
                             Ptr<Ipv4FlowClassifier> classifier,
                             uint16_t basePort,
                             uint32_t linkCount)
    : m_stepTime(stepTime),
      m_nodes(nodes),
      m_links(std::move(links)),
      m_nodeAddress(std::move(nodeAddress)),
      m_apps(std::move(apps)),
      m_flowRates(std::move(flowRates)),
      m_monitor(monitor),
      m_classifier(classifier),
      m_basePort(basePort),
      m_linkCount(linkCount),
      m_scalePercent(100),
      m_linkUp(linkCount, true),
      m_flowTotals(m_apps.size())
{
    Ipv4StaticRoutingHelper helper;
    const uint32_t n = m_nodes.GetN();
    m_fib.assign(n, std::vector<int32_t>(n, -1));
    for (uint32_t i = 0; i < n; ++i)
    {
        m_routing.push_back(helper.GetStaticRouting(m_nodes.Get(i)->GetObject<Ipv4>()));
    }
    for (uint32_t i = 0; i < m_links.size(); ++i)
    {
        m_portOf[{m_links[i].from, m_links[i].to}] = i;
    }
    Simulator::Schedule(Seconds(0), &RoutingGymEnv::ScheduleNextStep, this);
}

void
RoutingGymEnv::DoDispose()
{
    m_monitor = nullptr;
    m_classifier = nullptr;
    OpenGymEnv::DoDispose();
}

void
RoutingGymEnv::ScheduleNextStep()
{
    Simulator::Schedule(m_stepTime, &RoutingGymEnv::ScheduleNextStep, this);
    Notify();
}

uint32_t
RoutingGymEnv::ObservationSize() const
{
    return 1 + 4 * m_links.size() + 5 * m_apps.size();
}

Ptr<OpenGymSpace>
RoutingGymEnv::GetObservationSpace()
{
    std::vector<uint32_t> shape = {ObservationSize()};
    return CreateObject<OpenGymBoxSpace>(0.0F, 1e12F, shape, TypeNameGet<float>());
}

Ptr<OpenGymSpace>
RoutingGymEnv::GetActionSpace()
{
    const uint32_t n = m_nodes.GetN();
    std::vector<uint32_t> shape = {n * n + m_linkCount + 1};
    return CreateObject<OpenGymBoxSpace>(-1.0F, 100000.0F, shape, TypeNameGet<int32_t>());
}

bool
RoutingGymEnv::GetGameOver()
{
    return false;
}

float
RoutingGymEnv::GetReward()
{
    return 0.0F; // computed in Python from the observation
}

std::string
RoutingGymEnv::GetExtraInfo()
{
    return "";
}

Ptr<OpenGymDataContainer>
RoutingGymEnv::GetObservation()
{
    std::vector<uint32_t> shape = {ObservationSize()};
    Ptr<OpenGymBoxContainer<float>> box = CreateObject<OpenGymBoxContainer<float>>(shape);
    box->AddValue(static_cast<float>(Simulator::Now().GetSeconds()));

    const double interval = m_stepTime.GetSeconds();
    for (DirectedLink& link : m_links)
    {
        const uint32_t packets = link.queue->GetNPackets();
        const uint32_t bytes = link.queue->GetNBytes();
        const uint64_t receivedBytes = link.queue->GetTotalReceivedBytes();
        const uint32_t receivedPackets = link.queue->GetTotalReceivedPackets();
        const uint32_t droppedPackets = link.queue->GetTotalDroppedPackets();

        // The queue's "received" totals count only accepted packets, so bytes sent are
        // those accepted minus the growth in what is still waiting.
        const double sentBytes = static_cast<double>(receivedBytes - link.lastReceivedBytes) -
                                 (static_cast<double>(bytes) - link.lastQueueBytes);
        const double sentBits = 8.0 * std::max(0.0, sentBytes);
        const uint32_t arrivals = receivedPackets - link.lastReceivedPackets;
        const uint32_t drops = droppedPackets - link.lastDroppedPackets;
        const bool up = m_linkUp[link.linkIndex];

        const double queueFraction = static_cast<double>(packets) / link.queueLimit;
        const double utilization =
            up ? std::min(1.0, sentBits / (link.bitsPerSecond * interval)) : 0.0;
        // Queue drops only: packets on a failed link are lost after the queue.
        const double offered = arrivals + drops;
        const double loss = up ? (offered > 0 ? drops / offered : 0.0) : 1.0;
        const double delay = link.propagationSeconds + 8.0 * bytes / link.bitsPerSecond;

        box->AddValue(static_cast<float>(queueFraction));
        box->AddValue(static_cast<float>(utilization));
        box->AddValue(static_cast<float>(loss));
        box->AddValue(static_cast<float>(delay));

        link.lastReceivedBytes = receivedBytes;
        link.lastQueueBytes = bytes;
        link.lastReceivedPackets = receivedPackets;
        link.lastDroppedPackets = droppedPackets;
    }

    std::vector<FlowTotals> current(m_apps.size());
    for (const auto& [flowId, stats] : m_monitor->GetFlowStats())
    {
        const Ipv4FlowClassifier::FiveTuple tuple = m_classifier->FindFlow(flowId);
        if (tuple.destinationPort < m_basePort)
        {
            continue;
        }
        const uint32_t index = tuple.destinationPort - m_basePort;
        if (index < current.size())
        {
            current[index].tx += stats.txPackets;
            current[index].rx += stats.rxPackets;
            current[index].rxBytes += stats.rxBytes;
            current[index].delaySum += stats.delaySum.GetSeconds();
            current[index].jitterSum += stats.jitterSum.GetSeconds();
        }
    }
    for (uint32_t i = 0; i < current.size(); ++i)
    {
        box->AddValue(static_cast<float>(current[i].tx - m_flowTotals[i].tx));
        box->AddValue(static_cast<float>(current[i].rx - m_flowTotals[i].rx));
        box->AddValue(static_cast<float>(current[i].rxBytes - m_flowTotals[i].rxBytes));
        box->AddValue(static_cast<float>(current[i].delaySum - m_flowTotals[i].delaySum));
        box->AddValue(static_cast<float>(current[i].jitterSum - m_flowTotals[i].jitterSum));
    }
    m_flowTotals = current;
    return box;
}

void
RoutingGymEnv::SetLinkState(uint32_t link, bool up)
{
    if (m_linkUp[link] == up)
    {
        return;
    }
    m_linkUp[link] = up;
    // A dead link silently destroys packets, so they count as lost in FlowMonitor. Taking
    // the interface down instead would make senders fail before FlowMonitor sees them,
    // and would overstate delivery.
    for (DirectedLink& directed : m_links)
    {
        if (directed.linkIndex == link)
        {
            if (up)
            {
                directed.rxError->Disable();
            }
            else
            {
                directed.rxError->Enable();
            }
        }
    }
}

void
RoutingGymEnv::SetNextHop(uint32_t node, uint32_t dest, int32_t hop)
{
    // No route (-1, destination unreachable): keep the old one. Packets die on the failed
    // link and are counted, whereas removing the route would hide them at the sender.
    if (hop < 0 || hop == m_fib[node][dest])
    {
        return;
    }
    const auto port = m_portOf.find({node, static_cast<uint32_t>(hop)});
    NS_ABORT_MSG_IF(port == m_portOf.end(),
                    "next hop " << hop << " is not a neighbor of node " << node);

    Ptr<Ipv4StaticRouting> routing = m_routing[node];
    const Ipv4Address destination = m_nodeAddress[dest];
    for (uint32_t i = routing->GetNRoutes(); i > 0; --i)
    {
        const Ipv4RoutingTableEntry entry = routing->GetRoute(i - 1);
        if (entry.IsHost() && entry.GetDest() == destination)
        {
            routing->RemoveRoute(i - 1);
        }
    }
    const DirectedLink& link = m_links[port->second];
    routing->AddHostRouteTo(destination, link.nextHopIp, link.interface);
    m_fib[node][dest] = hop;
}

bool
RoutingGymEnv::ExecuteActions(Ptr<OpenGymDataContainer> action)
{
    Ptr<OpenGymBoxContainer<int32_t>> box = DynamicCast<OpenGymBoxContainer<int32_t>>(action);
    NS_ABORT_MSG_IF(!box, "expected an int32 action box");
    const std::vector<int32_t> values = box->GetData();
    const uint32_t n = m_nodes.GetN();
    NS_ABORT_MSG_IF(values.size() != n * n + m_linkCount + 1,
                    "action has " << values.size() << " values");

    for (uint32_t node = 0; node < n; ++node)
    {
        for (uint32_t dest = 0; dest < n; ++dest)
        {
            if (node != dest)
            {
                SetNextHop(node, dest, values[node * n + dest]);
            }
        }
    }
    for (uint32_t link = 0; link < m_linkCount; ++link)
    {
        SetLinkState(link, values[n * n + link] != 0);
    }
    const int32_t scale = values[n * n + m_linkCount];
    if (scale != m_scalePercent)
    {
        m_scalePercent = scale;
        for (uint32_t i = 0; i < m_apps.size(); ++i)
        {
            const double rate = std::max(1000.0, m_flowRates[i] * scale / 100.0);
            m_apps[i]->SetAttribute("DataRate", DataRateValue(DataRate(static_cast<uint64_t>(rate))));
        }
    }
    return true;
}

} // namespace ns3
