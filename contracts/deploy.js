// Hardhat deployment script — GiskardMarks on Arbitrum One
// Run: npx hardhat run contracts/deploy.js --network arbitrum
//
// Required in hardhat.config.js:
//   networks: {
//     arbitrum: {
//       url: "https://arb1.arbitrum.io/rpc",
//       accounts: [process.env.PRIVATE_KEY]
//     }
//   }

async function main() {
  const [deployer] = await ethers.getSigners();
  console.log("Deploying GiskardMarks with:", deployer.address);
  console.log("Balance:", (await deployer.getBalance()).toString());

  const GiskardMarks = await ethers.getContractFactory("GiskardMarks");
  const contract = await GiskardMarks.deploy();
  await contract.deployed();

  console.log("GiskardMarks deployed to:", contract.address);
  console.log("Verify on Arbiscan: https://arbiscan.io/address/" + contract.address);
  console.log("\nUpdate ARBITRUM_CONTRACT in marks.py with:", contract.address);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
