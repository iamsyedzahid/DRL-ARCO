/* SPDX-License-Identifier: GPL-2.0-only */
// The 10-node DRL-ARCO scenario. Python normally supplies --links and --flows from
// configs/default.yaml; the defaults below are identical (tests/test_config_sync.py checks)
// so the scenario can also be started by hand for debugging.
#include "routing-gym-env.h"

#include <algorithm>
#include <sstream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("DrlArco");

namespace
{

const char* const kDefaultLinks =
    "0-1:10:4,0-2:10:4,0-3:20:2,1-3:10:2,2-3:10:2,1-4:10:4,2-6:10:4,3-5:20:2,"
    "4-5:10:2,5-6:10:2,5-7:20:2,4-8:10:4,6-9:10:4,7-8:10:2,7-9:10:2,8-9:10:3";

const char* const kDefaultFlows =
    "0-7:6:0.6:0.4,0-8:5:0.6:0.4,0-9:5:0.6:0.4,1-7:5:0.8:0.5,1-9:4:0.4:0.3,2-7:5:0.8:0.5,"
    "2-8:4:0.4:0.3,3-7:4:1:0.6,9-0:4:0.6:0.4,8-1:3:0.6:0.4,7-2:4:0.6:0.4,4-6:2:0.5:0.5";

const uint32_t kNodeCount = 10;
const uint16_t kBasePort = 9000;

struct LinkSpec
{
    uint32_t u;
    uint32_t v;
    double mbps;
    double delayMs;
};

struct FlowSpec
{
    uint32_t src;
    uint32_t dst;
    double mbps;
    double onSeconds;
    double offSeconds;
};

/** Split "a-b:c:d,..." into one numeric vector per entry. */
std::vector<std::vector<double>>
ParseTable(const std::string& text)
{
    std::vector<std::vector<double>> table;
    std::stringstream rows(text);
    std::string row;
    while (std::getline(rows, row, ','))
    {
        std::replace(row.begin(), row.end(), '-', ' ');
        std::replace(row.begin(), row.end(), ':', ' ');
        std::stringstream cells(row);
        std::vector<double> values;
        double value;
        while (cells >> value)
        {
            values.push_back(value);
        }
        table.push_back(values);
    }
    return table;
}

std::vector<LinkSpec>
ParseLinks(const std::string& text)
{
    std::vector<LinkSpec> links;
    for (const auto& r : ParseTable(text))
    {
        NS_ABORT_MSG_IF(r.size() != 4, "bad --links entry");
        links.push_back({static_cast<uint32_t>(r[0]), static_cast<uint32_t>(r[1]), r[2], r[3]});
    }
    return links;
}

std::vector<FlowSpec>
ParseFlows(const std::string& text)
{
    std::vector<FlowSpec> flows;
    for (const auto& r : ParseTable(text))
    {
        NS_ABORT_MSG_IF(r.size() != 5, "bad --flows entry");
        flows.push_back(
            {static_cast<uint32_t>(r[0]), static_cast<uint32_t>(r[1]), r[2], r[3], r[4]});
    }
    return flows;
}

std::string
Exponential(double mean)
{
    std::ostringstream text;
    text << "ns3::ExponentialRandomVariable[Mean=" << mean << "]";
    return text.str();
}

} // namespace

int
main(int argc, char* argv[])
{
    uint32_t openGymPort = 5555;
    uint32_t simSeed = 1;
    double simTime = 30.1;
    double stepTime = 0.1;
    uint32_t packetBytes = 1000;
    uint32_t queuePackets = 100;
    std::string linksArg = kDefaultLinks;
    std::string flowsArg = kDefaultFlows;

    CommandLine cmd(__FILE__);
    cmd.AddValue("openGymPort", "Port of the Python agent", openGymPort);
    cmd.AddValue("simSeed", "Run number for the random streams", simSeed);
    cmd.AddValue("simTime", "Simulated seconds", simTime);
    cmd.AddValue("stepTime", "Seconds between routing decisions", stepTime);
    cmd.AddValue("packetBytes", "UDP payload size", packetBytes);
    cmd.AddValue("queuePackets", "DropTail queue size per interface", queuePackets);
    cmd.AddValue("links", "u-v:mbps:delayMs,...", linksArg);
    cmd.AddValue("flows", "src-dst:mbps:onSeconds:offSeconds,...", flowsArg);
    cmd.Parse(argc, argv);

    RngSeedManager::SetSeed(1);
    RngSeedManager::SetRun(simSeed);

    const std::vector<LinkSpec> linkSpecs = ParseLinks(linksArg);
    const std::vector<FlowSpec> flowSpecs = ParseFlows(flowsArg);

    NodeContainer nodes;
    nodes.Create(kNodeCount);

    // Static routing only: the Python agent owns every forwarding decision.
    Ipv4StaticRoutingHelper staticRouting;
    InternetStackHelper internet;
    internet.SetRoutingHelper(staticRouting);
    internet.Install(nodes);

    std::vector<DirectedLink> directedLinks;
    std::vector<Ipv4Address> nodeAddress(kNodeCount, Ipv4Address::GetAny());
    TrafficControlHelper trafficControl;

    for (uint32_t i = 0; i < linkSpecs.size(); ++i)
    {
        const LinkSpec& spec = linkSpecs[i];
        PointToPointHelper p2p;
        std::ostringstream rate;
        std::ostringstream delay;
        std::ostringstream limit;
        rate << spec.mbps << "Mbps";
        delay << spec.delayMs << "ms";
        limit << queuePackets << "p";
        p2p.SetDeviceAttribute("DataRate", StringValue(rate.str()));
        p2p.SetChannelAttribute("Delay", StringValue(delay.str()));
        p2p.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", StringValue(limit.str()));
        NetDeviceContainer devices = p2p.Install(nodes.Get(spec.u), nodes.Get(spec.v));

        std::ostringstream subnet;
        subnet << "10.1." << i << ".0";
        Ipv4AddressHelper addresses;
        addresses.SetBase(subnet.str().c_str(), "255.255.255.252");
        Ipv4InterfaceContainer interfaces = addresses.Assign(devices);
        // Assign() installs a default queue disc. Remove it so that each device's DropTail
        // queue is the one bottleneck buffer, which is the queue we measure.
        trafficControl.Uninstall(devices);

        const uint32_t ends[2] = {spec.u, spec.v};
        for (uint32_t side = 0; side < 2; ++side)
        {
            const uint32_t node = ends[side];
            if (nodeAddress[node] == Ipv4Address::GetAny())
            {
                nodeAddress[node] = interfaces.GetAddress(side);
            }

            Ptr<RateErrorModel> rxError = CreateObject<RateErrorModel>();
            rxError->SetUnit(RateErrorModel::ERROR_UNIT_PACKET);
            rxError->SetRate(1.0);
            rxError->Disable();
            devices.Get(1 - side)->SetAttribute("ReceiveErrorModel", PointerValue(rxError));

            Ptr<PointToPointNetDevice> device =
                DynamicCast<PointToPointNetDevice>(devices.Get(side));
            DirectedLink directed;
            directed.from = node;
            directed.to = ends[1 - side];
            directed.linkIndex = i;
            directed.interface = interfaces.Get(side).second;
            directed.nextHopIp = interfaces.GetAddress(1 - side);
            directed.bitsPerSecond = spec.mbps * 1e6;
            directed.propagationSeconds = spec.delayMs / 1000.0;
            directed.queue = device->GetQueue();
            directed.rxError = rxError;
            directed.queueLimit = queuePackets;
            directed.lastReceivedBytes = 0;
            directed.lastQueueBytes = 0;
            directed.lastReceivedPackets = 0;
            directed.lastDroppedPackets = 0;
            directedLinks.push_back(directed);
        }
    }

    // The heterogeneous On-Off sources (Feature 4). Each flow's port identifies it later.
    std::vector<Ptr<OnOffApplication>> apps;
    std::vector<double> flowRates;
    for (uint32_t i = 0; i < flowSpecs.size(); ++i)
    {
        const FlowSpec& flow = flowSpecs[i];
        const uint16_t port = kBasePort + i;

        PacketSinkHelper sink("ns3::UdpSocketFactory",
                              InetSocketAddress(Ipv4Address::GetAny(), port));
        sink.Install(nodes.Get(flow.dst)).Start(Seconds(0.0));

        OnOffHelper source("ns3::UdpSocketFactory",
                           InetSocketAddress(nodeAddress[flow.dst], port));
        source.SetAttribute("DataRate", DataRateValue(DataRate(static_cast<uint64_t>(flow.mbps * 1e6))));
        source.SetAttribute("PacketSize", UintegerValue(packetBytes));
        source.SetAttribute("OnTime", StringValue(Exponential(flow.onSeconds)));
        source.SetAttribute("OffTime", StringValue(Exponential(flow.offSeconds)));
        ApplicationContainer installed = source.Install(nodes.Get(flow.src));
        installed.Start(Seconds(0.05));
        apps.push_back(DynamicCast<OnOffApplication>(installed.Get(0)));
        flowRates.push_back(flow.mbps * 1e6);
    }

    FlowMonitorHelper flowHelper;
    Ptr<FlowMonitor> monitor = flowHelper.InstallAll();
    Ptr<Ipv4FlowClassifier> classifier =
        DynamicCast<Ipv4FlowClassifier>(flowHelper.GetClassifier());

    Ptr<OpenGymInterface> openGym = CreateObject<OpenGymInterface>(openGymPort);
    Ptr<RoutingGymEnv> env = CreateObject<RoutingGymEnv>(Seconds(stepTime),
                                                         nodes,
                                                         directedLinks,
                                                         nodeAddress,
                                                         apps,
                                                         flowRates,
                                                         monitor,
                                                         classifier,
                                                         kBasePort,
                                                         static_cast<uint32_t>(linkSpecs.size()));
    env->SetOpenGymInterface(openGym);

    Simulator::Stop(Seconds(simTime));
    Simulator::Run();
    openGym->NotifySimulationEnd();
    Simulator::Destroy();
    return 0;
}
